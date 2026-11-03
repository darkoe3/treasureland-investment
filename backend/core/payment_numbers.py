"""Agency-scoped payment number search and atomic creation; no register management access."""
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as ModelValidationError
from django.db.models import Q, Sum, Count, Max
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from .models import (Agency, AgentType, AuditLog, PaymentPayer, PaymentObligation,
                     PayerPayment, PayerSubAgentAssignment, Person, TPMCode, TerminalNumber, money)


class NumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


def validate_number(number, payer, agency):
    if not agency.is_active or not payer.is_active or payer.agency_id != agency.pk:
        raise ValidationError({"sub_agent_number": "Select an active payer in the selected active agency."})
    if not number.is_active or not number.person.is_active or number.person.agency_id != agency.pk:
        raise ValidationError({"sub_agent_number": "Select an active Sub-Agent Number in this agency."})
    if not PayerSubAgentAssignment.objects.filter(payer=payer, sub_agent_number=number, is_active=True).exists():
        raise ValidationError({"sub_agent_number": "Select a number assigned to this payer. Use the controlled Reassign workflow to change ownership."})
    terminal = number.terminal_numbers.filter(is_active=True).first()
    if terminal and (terminal.agency_id != agency.pk or terminal.person_id != number.person_id):
        raise ValidationError({"sub_agent_number": "Terminal assignment does not match this agency and owner."})
    if not terminal and number.terminal_numbers.exists():
        raise ValidationError({"sub_agent_number": "Inactive Terminal assignments cannot be selected."})
    return terminal


def filter_numbers(queryset, params, prefix=""):
    number = params.get("sub_agent_number")
    if number:
        if not str(number).isdigit():
            raise ValidationError({"sub_agent_number": "Use a numeric record ID."})
        queryset = queryset.filter(**{prefix + "sub_agent_number_id": number})
    for field in ("sub_agent_number_snapshot", "terminal_number_snapshot"):
        value = params.get(field) or (params.get("terminal_number") if field == "terminal_number_snapshot" else None)
        if value:
            queryset = queryset.filter(**{prefix + field + "__icontains": str(value)[:80]})
    return queryset


def totals(obligations, payments=None):
    payments = payments if payments is not None else PayerPayment.objects.filter(obligation__in=obligations)
    amounts = payments.aggregate(gross=Sum("amount_received"), reversed=Sum("amount_received", filter=Q(status="REVERSED")), last=Max("payment_date"), count=Count("pk"))
    expected = obligations.aggregate(value=Sum("total_expected"))["value"] or 0
    outstanding = obligations.filter(status__in=["OPEN", "PARTIALLY_PAID"])
    outstanding_expected = outstanding.aggregate(value=Sum("total_expected"))["value"] or 0
    outstanding_paid = PayerPayment.objects.filter(obligation__in=outstanding, status="POSTED").aggregate(value=Sum("amount_received"))["value"] or 0
    gross, reversed_amount = money(amounts["gross"]), money(amounts["reversed"])
    return {"total_expected": str(money(expected)), "gross_posted_amount": str(gross), "reversed_amount": str(reversed_amount),
            "net_collected_amount": str(money(gross - reversed_amount)), "outstanding_balance": str(money(outstanding_expected - outstanding_paid)),
            "open_obligation_count": outstanding.count(), "obligation_count": obligations.count(), "payment_count": amounts["count"],
            "last_payment_date": amounts["last"]}


def number_result(assignment):
    number, payer = assignment.sub_agent_number, assignment.payer
    terminal = number.terminal_numbers.filter(is_active=True).first() or number.terminal_numbers.order_by("-id").first()
    try:
        validate_number(number, payer, payer.agency)
        eligible = assignment.is_active
    except ValidationError:
        eligible = False
    return {"id": number.pk, "sub_agent_number": number.code, "payer": payer.pk, "payer_name": payer.payer_name,
            "agency": payer.agency_id, "agency_name": payer.agency.name,
            "terminal_number": terminal.terminal_number if terminal else "", "terminal_id": terminal.pk if terminal else None,
            "is_active": eligible, "selectable": eligible,
            **totals(PaymentObligation.objects.filter(sub_agent_number=number, payer=payer))}


class QuickCreateInput(serializers.Serializer):
    agency = serializers.IntegerField(min_value=1, required=False)
    payer = serializers.IntegerField(min_value=1)
    sub_agent_number = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$", max_length=80)
    terminal_number = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$", max_length=80)
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("Explicit confirmation is required.")
        return value


def duplicate_error(code, terminal, agency):
    existing = TPMCode.objects.select_related("person__agency").filter(code__iexact=code).first()
    if existing:
        # Never disclose another agency's owner through duplicate probing.
        if existing.person.agency_id != agency.pk:
            raise ValidationError({"sub_agent_number": "Sub-Agent Number already exists in another agency. Use the controlled Reassign workflow; quick creation cannot reassign it."})
        assignment = existing.payment_payer_assignments.filter(is_active=True).select_related("payer").first()
        name = assignment.payer.payer_name if assignment else existing.person.full_name
        raise ValidationError({"sub_agent_number": f"Sub-Agent Number {existing.code} already exists and is assigned to {name} in {existing.person.agency.name}. Select or edit the existing record. Use the controlled Reassign workflow for a different payer."})
    existing = TerminalNumber.objects.select_related("sub_agent_number", "person").filter(terminal_number__iexact=terminal).first()
    if existing:
        if existing.agency_id != agency.pk:
            raise ValidationError({"terminal_number": "Terminal Number already exists in another agency. Use the controlled Reassign workflow; quick creation cannot reassign it."})
        assignment = existing.sub_agent_number.payment_payer_assignments.filter(is_active=True).select_related("payer").first()
        name = assignment.payer.payer_name if assignment else existing.person.full_name
        raise ValidationError({"terminal_number": f"Terminal Number {existing.terminal_number} already exists and is assigned to Sub-Agent Number {existing.sub_agent_number.code} for {name}. Use the controlled Reassign workflow for a different payer."})


class PaymentNumbersView(APIView):
    permission_classes = [IsAuthenticated]

    def agency(self, request, agency_id):
        from .views import require_assignment_flag
        agency = get_object_or_404(Agency, pk=agency_id)
        require_assignment_flag(request.user, agency, "can_edit")
        return agency

    def get(self, request, agency_id):
        agency = self.agency(request, agency_id)
        search = request.query_params.get("search", "").strip()
        if len(search) > 100:
            raise ValidationError({"search": "Search must be at most 100 characters."})
        assignments = PayerSubAgentAssignment.objects.filter(payer__agency=agency, sub_agent_number__person__agency=agency).select_related("payer__agency", "sub_agent_number__person__agency")
        if search:
            assignments = assignments.filter(Q(sub_agent_number__code__icontains=search) | Q(payer__payer_name__icontains=search) | Q(sub_agent_number__terminal_numbers__terminal_number__icontains=search))
        else:
            assignments = assignments.none()
        assignments = assignments.order_by("sub_agent_number__code", "payer_id", "id").distinct()
        paginator = NumberPagination()
        rows = paginator.paginate_queryset(assignments, request)
        results = [number_result(row) for row in rows]
        # An inactive terminal search must not select its replacement assignment.
        for row in results:
            if search and TerminalNumber.objects.filter(sub_agent_number_id=row["id"], terminal_number__icontains=search, is_active=False).exists() and not TerminalNumber.objects.filter(sub_agent_number_id=row["id"], terminal_number__icontains=search, is_active=True).exists() and search.lower() not in row["sub_agent_number"].lower() and search.lower() not in row["payer_name"].lower():
                row["selectable"] = False
                row["is_active"] = False
        return paginator.get_paginated_response(results)

    def post(self, request, agency_id):
        agency = self.agency(request, agency_id)
        serializer = QuickCreateInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("agency", agency.pk) != agency.pk:
            raise ValidationError({"agency": "Selected agency must match the agency in the request path."})
        try:
            with transaction.atomic():
                from .terminal_register import lock_register
                lock_register()
                agency = self.agency(request, agency_id)
                payer = get_object_or_404(PaymentPayer.objects.select_for_update(), pk=data["payer"], agency=agency, is_active=True)
                duplicate_error(data["sub_agent_number"], data["terminal_number"], agency)
                person = register_person(payer)
                number = TPMCode.objects.create(person=person, code=data["sub_agent_number"])
                terminal = TerminalNumber.objects.create(terminal_number=data["terminal_number"], sub_agent_number=number, person=person, agency=agency, created_by=request.user, updated_by=request.user)
                assignment = PayerSubAgentAssignment.objects.create(payer=payer, sub_agent_number=number, assigned_by=request.user)
                metadata = {"agency_id": agency.pk, "payer_id": payer.pk, "person_id": person.pk, "sub_agent_number_id": number.pk, "terminal_number_id": terminal.pk, "actor_id": request.user.pk, "source": "PAYMENT_QUICK_CREATE"}
                for obj, action in ((number, "PAYMENT_NUMBER_CREATED"), (terminal, "PAYMENT_TERMINAL_CREATED")):
                    AuditLog.objects.create(user=request.user, agency=agency, action=action, model_name=type(obj).__name__, object_id=str(obj.pk), new_values=metadata)
                result = number_result(assignment)
        except ModelValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
        except IntegrityError:
            duplicate_error(data["sub_agent_number"], data["terminal_number"], agency)
            raise ValidationError({"detail": "Assignment changed concurrently. Search again before retrying."})
        return Response(result, status=201)


class PayerNumbersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, payer_id):
        from .views import ensure_agency_filter_access
        payer = get_object_or_404(PaymentPayer, pk=payer_id)
        ensure_agency_filter_access(request.user, [payer.agency_id])
        rows = payer.sub_agent_assignments.select_related("payer__agency", "sub_agent_number__person__agency").order_by("sub_agent_number__code", "id")
        paginator = NumberPagination()
        return paginator.get_paginated_response([number_result(row) for row in paginator.paginate_queryset(rows, request)])


def register_person(payer):
    if payer.register_person_id:
        person = Person.objects.select_for_update().get(pk=payer.register_person_id)
    else:
        owners = list(Person.objects.filter(tpm_codes__payment_payer_assignments__payer=payer,
                      tpm_codes__payment_payer_assignments__is_active=True).distinct()[:2])
        if len(owners) == 1:
            person = owners[0]
        else:
            # Explicit payer identity, never a name-based lookup or typed-text payer.
            person = Person.objects.create(agency=payer.agency, full_name=payer.payer_name, agent_type=AgentType.SUBAGENT)
        payer.register_person = person
        payer.save(update_fields=["register_person", "updated_at"])
    if person.agency_id != payer.agency_id or not person.is_active:
        raise ValidationError({"payer": "The linked register person must be active and in this agency."})
    return person


def number_breakdown(obligations, payments, request):
    groups = obligations.values("sub_agent_number_id", "payer_id", "agency_id").distinct().order_by("sub_agent_number_id", "payer_id", "agency_id")
    paginator = NumberPagination()
    rows = paginator.paginate_queryset(groups, request)
    result = []
    for row in rows:
        selected = obligations.filter(**{key: row[key] for key in ("sub_agent_number_id", "payer_id", "agency_id")})
        latest = selected.select_related("payer", "agency").order_by("-obligation_date", "-pk").first()
        identity = {"sub_agent_number_snapshot": latest.sub_agent_number_snapshot,
                    "terminal_number_snapshot": latest.terminal_number_snapshot,
                    "payer_name_snapshot": latest.payer_name_snapshot or latest.payer.payer_name,
                    "agency_name_snapshot": latest.agency_name_snapshot or latest.agency.name}
        result.append({**row, **identity, **totals(selected, payments.filter(obligation__in=selected))})
    return {"count": paginator.page.paginator.count, "next": paginator.get_next_link(), "previous": paginator.get_previous_link(), "results": result}
