from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import logging
import uuid
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpResponse
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .agencies import AgencyWriteLockMixin, require_active_agency, agency_counts, agency_identity, agency_audit
from .models import (
    Agency,
    AuditAction,
    AuditLog,
    DailySheet,
    DailySheetImportBatch,
    DailySheetImportStatus,
    DailySheetStatus,
    Game,
    OmittedTerminal,
    PaymentObligation,
    PaymentPayer,
    PayerPayment,
    PayerSubAgentAssignment,
    Person,
    TPMCode,
    TPMDailyTransaction,
    TransactionGameSale,
    User,
    UserAgencyAssignment,
    UserRole,
    WeeklyGameSchedule,
    json_safe_value,
    money,
)
from .importers import build_daily_sheet_template, parse_daily_sheet_workbook
from .permissions import IsSuperAdmin, SuperAdminOnlyWrites, SuperAdminOrReadOnlyAccountant
from .reports import build_report, serialize_report, workbook_response
from .serializers import (
    AgencySerializer,
    AccountantCreateSerializer,
    AccountantPasswordResetSerializer,
    AccountantSerializer,
    AccountantSetAgenciesSerializer,
    AccountantUpdateSerializer,
    AuditLogSerializer,
    CurrentUserSerializer,
    DailySheetGameSerializer,
    DailySheetImportBatchSerializer,
    DailySheetSerializer,
    EmailTokenObtainPairSerializer,
    GameSerializer,
    OmittedTerminalSerializer,
    PaymentObligationSerializer,
    PaymentPayerSerializer,
    PayerPaymentSerializer,
    PayerSubAgentAssignmentSerializer,
    PersonSerializer,
    TPMCodeSerializer,
    TPMDailyTransactionSerializer,
    UserAgencyAssignmentSerializer,
    WeeklyGameScheduleSerializer,
)


logger = logging.getLogger(__name__)


def log_import_confirmation_error(exc, level):
    reference = uuid.uuid4().hex[:12]
    locations = []
    traceback = exc.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith("core."):
            locations.append(
                f"{module.replace('.', '/')}.py:{traceback.tb_lineno}:{traceback.tb_frame.f_code.co_name}"
            )
        traceback = traceback.tb_next
    # Keep the reference in the message so ordinary console formatters emit it.
    # Never log exception messages, source text, frame locals or request/batch data.
    logger.log(
        level, "Daily sheet import confirmation failed reference=%s exception=%s location=%s",
        reference, type(exc).__name__, ";".join(locations),
    )
    return reference


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token_refresh"


@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    refresh_token = request.data.get("refresh")
    if not refresh_token:
        return Response({"detail": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        RefreshToken(refresh_token).blacklist()
    except TokenError:
        return Response({"detail": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user_view(request):
    user = User.objects.prefetch_related("agency_assignments__agency").get(pk=request.user.pk)
    return Response(CurrentUserSerializer(user).data)


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def agency_summary_report_view(request):
    report = build_report(request.query_params, request.user, AuditAction.REPORT_PREVIEWED)
    return Response(serialize_report(report))


@api_view(["GET"])
@permission_classes([IsSuperAdmin])
def agency_summary_report_export_view(request):
    report = build_report(request.query_params, request.user, AuditAction.REPORT_EXPORTED)
    return workbook_response(report)


class BaseSearchViewSet(AgencyWriteLockMixin, viewsets.ModelViewSet):
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]


class PaymentPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


def parse_payment_date(value, field_name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Use an ISO date in YYYY-MM-DD format."}) from exc


def validate_date_range(query_params, start_name, end_name):
    start = parse_payment_date(query_params[start_name], start_name) if query_params.get(start_name) else None
    end = parse_payment_date(query_params[end_name], end_name) if query_params.get(end_name) else None
    if start and end and start > end:
        raise ValidationError({end_name: f"{end_name} must be on or after {start_name}."})
    return start, end


def parse_id_filter(query_params, name):
    values = query_params.getlist(name)
    if not values:
        return []
    parsed = []
    for value in values:
        for item in value.split(","):
            try:
                parsed.append(int(item))
            except (TypeError, ValueError) as exc:
                raise ValidationError({name: "Use numeric IDs separated by commas."}) from exc
    return list(dict.fromkeys(parsed))


def parse_single_id(query_params, name):
    value = query_params.get(name)
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Use a numeric ID."}) from exc


def validate_ordering(query_params, allowed):
    ordering = query_params.get("ordering")
    if not ordering:
        return
    invalid = [item for item in ordering.split(",") if item.lstrip("-") not in allowed]
    if invalid:
        raise ValidationError({"ordering": "Unsupported ordering field."})


def ensure_agency_filter_access(user, agency_ids):
    if user.role == UserRole.SUPER_ADMIN or not agency_ids:
        return
    accessible = set(accessible_agency_ids(user).filter(agency__is_active=True))
    if not set(agency_ids).issubset(accessible):
        raise PermissionDenied("You do not have access to one or more requested agencies.")


class PaymentQueryMixin:
    pagination_class = PaymentPagination

    def filter_queryset(self, queryset):
        validate_ordering(self.request.query_params, set(self.ordering_fields))
        return super().filter_queryset(queryset)

    def validate_agency_query(self):
        agency_ids = parse_id_filter(self.request.query_params, "agency")
        ensure_agency_filter_access(self.request.user, agency_ids)
        return agency_ids


def assignment_for(user, agency):
    if user.role == UserRole.SUPER_ADMIN:
        return None
    return UserAgencyAssignment.objects.filter(user=user, agency=agency).first()


def require_assignment_flag(user, agency, flag):
    if flag in {"can_create", "can_edit", "can_delete"}:
        require_active_agency(agency)
    if user.role == UserRole.SUPER_ADMIN:
        return
    assignment = assignment_for(user, agency)
    if not assignment or not getattr(assignment, flag):
        raise PermissionDenied(f"You do not have {flag} permission for this agency.")


def accessible_agency_ids(user, flag=None):
    if user.role == UserRole.SUPER_ADMIN:
        return None
    queryset = UserAgencyAssignment.objects.filter(user=user)
    if flag:
        queryset = queryset.filter(**{flag: True})
    return queryset.values_list("agency_id", flat=True)


def log_audit(user, agency, action, model_name, object_id, old_values=None, new_values=None, description="", daily_sheet=None):
    def clean(values):
        return {key: json_safe_value(value) for key, value in (values or {}).items()}

    AuditLog.objects.create(
        user=user,
        agency=agency,
        daily_sheet=daily_sheet,
        action=action,
        model_name=model_name,
        object_id=str(object_id),
        old_values=clean(old_values),
        new_values=clean(new_values),
        description=description,
    )


def validate_sheet_submission(sheet):
    if sheet.incoming_funds is None:
        raise ValidationError({"incoming_funds": "Incoming funds must be entered before submission."})
    if sheet.tax is None:
        raise ValidationError({"tax": "Tax must be entered before submission, including zero when no tax applies."})
    if not sheet.sheet_games.exists():
        raise ValidationError({"sheet_games": "At least one game must exist on the sheet."})
    active_tpm_ids = set(
        TPMCode.objects.filter(person__agency=sheet.agency, person__is_active=True, is_active=True).values_list("id", flat=True)
    )
    entered_ids = set(sheet.transactions.values_list("tpm_code_id", flat=True))
    omitted_ids = set(sheet.omitted_terminals.filter(is_active=True).values_list("tpm_code_id", flat=True))
    unexplained = active_tpm_ids - entered_ids - omitted_ids
    if unexplained:
        raise ValidationError({"omitted_terminals": "Every active Sub-Agent Number must be entered or omitted with an explanation."})
    if entered_ids & omitted_ids:
        raise ValidationError({"tpm_code": "A Sub-Agent Number cannot be both entered and omitted."})
    game_count = sheet.sheet_games.count()
    for tpm_transaction in sheet.transactions.all():
        if tpm_transaction.sales.count() != game_count:
            raise ValidationError({"sales": "Every transaction must have one sale entry for every game on the sheet."})
    if sheet.transactions.values("tpm_code").distinct().count() != sheet.transactions.count():
        raise ValidationError({"tpm_code": "Duplicate Sub-Agent Numbers are not allowed."})
    if sheet.totals()["variance"] != 0 and not sheet.reconciliation_note.strip():
        raise ValidationError({"reconciliation_note": "A reconciliation note is required when variance is not zero."})


class AgencyViewSet(BaseSearchViewSet):
    serializer_class = AgencySerializer
    permission_classes = [SuperAdminOrReadOnlyAccountant]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]

    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = Agency.objects.all()
        if self.request.user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(user_assignments__user=self.request.user).distinct()
        active = self.request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    def _save(self, serializer, action_name):
        previous = agency_identity(serializer.instance) if serializer.instance else None
        try:
            with transaction.atomic():
                agency = serializer.save()
                agency_audit(self.request.user, agency, action_name, previous)
        except IntegrityError:
            # A concurrent create may win after serializer uniqueness validation.
            retry = self.get_serializer(serializer.instance, data=self.request.data, partial=True)
            retry.is_valid(raise_exception=True)
            raise ValidationError({"detail": "An agency with this name or code already exists. Refresh and try again."})

    def perform_create(self, serializer):
        self._save(serializer, AuditAction.AGENCY_CREATED)

    def perform_update(self, serializer):
        self._save(serializer, AuditAction.AGENCY_UPDATED)

    def retrieve(self, request, *args, **kwargs):
        agency = self.get_object()
        data = dict(self.get_serializer(agency).data)
        data["assigned_accountants"] = list(agency.user_assignments.values("user_id", "user__full_name"))
        data["recent_daily_sheets"] = list(agency.daily_sheets.values("id", "transaction_date", "status")[:10])
        events = agency.audit_logs.all()
        if request.user.role != UserRole.SUPER_ADMIN:
            assignment = assignment_for(request.user, agency)
            events = events.exclude(model_name__in=["TerminalNumber", "TerminalImportBatch"]) if assignment and assignment.can_view_history else events.none()
        data["recent_audit_events"] = list(events.values("id", "action", "created_at")[:10])
        return Response(data)

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        return Response(agency_counts(self.get_object()))

    def _change_status(self, request, active):
        agency = self.get_object()  # Parent lock acquired before any mutation/child lock.
        reason = request.data.get("reason")
        errors = {}
        if not isinstance(reason, str) or not reason.strip():
            errors["reason"] = "A reason is required."
        elif len(reason.strip()) > 1000:
            errors["reason"] = "Use at most 1000 characters."
        if request.data.get("confirmed") is not True:
            errors["confirmed"] = "Explicit confirmation is required."
        impact = agency_counts(agency)
        if not active and impact["editable_daily_sheets"] and request.data.get("acknowledge_editable_sheets") is not True:
            errors["acknowledge_editable_sheets"] = "Acknowledge the Draft, Returned or Reopened sheets. They will be preserved."
        if errors:
            raise ValidationError(errors)
        if agency.is_active == active:
            return Response({"detail": "Agency status has already changed. Refresh before continuing."}, status=409)
        previous = agency_identity(agency)
        agency.is_active = active
        agency.save(update_fields=["is_active", "updated_at"])
        agency_audit(request.user, agency, AuditAction.AGENCY_REACTIVATED if active else AuditAction.AGENCY_DEACTIVATED,
                     previous, reason.strip(), impact)
        return Response(self.get_serializer(agency).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._change_status(request, False)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._change_status(request, True)


class UserAgencyAssignmentViewSet(BaseSearchViewSet):
    serializer_class = UserAgencyAssignmentSerializer
    permission_classes = [SuperAdminOnlyWrites]
    search_fields = ["user__email", "user__full_name", "agency__name", "agency__code"]
    ordering_fields = ["created_at", "agency__name", "user__email"]

    def get_queryset(self):
        queryset = UserAgencyAssignment.objects.select_related("user", "agency", "assigned_by")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)


class AccountantViewSet(BaseSearchViewSet):
    permission_classes = [IsSuperAdmin]
    throttle_scope = None
    search_fields = ["email", "full_name", "agency_assignments__agency__name"]
    ordering_fields = ["email", "full_name", "created_at", "is_active"]

    def get_queryset(self):
        return (
            User.objects.filter(role=UserRole.ACCOUNTANT)
            .prefetch_related("agency_assignments__agency")
            .order_by("email")
            .distinct()
        )

    def get_serializer_class(self):
        if self.action == "create":
            return AccountantCreateSerializer
        if self.action in {"partial_update", "update"}:
            return AccountantUpdateSerializer
        return AccountantSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        active = request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        page = self.paginate_queryset(queryset)
        serializer = AccountantSerializer(page if page is not None else queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def perform_create(self, serializer):
        user = serializer.save()
        log_audit(
            self.request.user,
            None,
            "ACCOUNTANT_CREATED",
            "User",
            user.id,
            new_values={"email": user.email, "full_name": user.full_name, "is_active": user.is_active},
            description=f"Accountant created: {user.email}",
        )

    def perform_update(self, serializer):
        user = self.get_object()
        old_values = {"email": user.email, "full_name": user.full_name, "is_active": user.is_active, "role": user.role}
        updated = serializer.save(role=UserRole.ACCOUNTANT, is_staff=False, is_superuser=False)
        log_audit(
            self.request.user,
            None,
            "ACCOUNTANT_UPDATED",
            "User",
            updated.id,
            old_values=old_values,
            new_values={"email": updated.email, "full_name": updated.full_name, "is_active": updated.is_active, "role": updated.role},
            description=f"Accountant updated: {updated.email}",
        )

    @action(detail=True, methods=["post"], url_path="set-agencies")
    def set_agencies(self, request, pk=None):
        accountant = self.get_object()
        serializer = AccountantSetAgenciesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignments = serializer.validated_data["agency_assignments"]
        with transaction.atomic():
            old_values = [
                {
                    "agency": item.agency_id,
                    "can_create": item.can_create,
                    "can_edit": item.can_edit,
                    "can_delete": item.can_delete,
                    "can_export": item.can_export,
                    "can_view_history": item.can_view_history,
                }
                for item in accountant.agency_assignments.select_related("agency")
            ]
            accountant.agency_assignments.all().delete()
            new_values = []
            for item in assignments:
                assignment = UserAgencyAssignment.objects.create(
                    user=accountant,
                    agency=item["agency"],
                    can_create=item["can_create"],
                    can_edit=item["can_edit"],
                    can_delete=item["can_delete"],
                    can_export=item["can_export"],
                    can_view_history=item["can_view_history"],
                    assigned_by=request.user,
                )
                assignment_values = {
                    "accountant": accountant.id,
                    "agency": assignment.agency_id,
                    "can_create": assignment.can_create,
                    "can_edit": assignment.can_edit,
                    "can_delete": assignment.can_delete,
                    "can_export": assignment.can_export,
                    "can_view_history": assignment.can_view_history,
                }
                new_values.append(assignment_values)
                log_audit(
                    request.user,
                    assignment.agency,
                    "ACCOUNTANT_AGENCY_ASSIGNED",
                    "UserAgencyAssignment",
                    assignment.id,
                    new_values=assignment_values,
                    description=f"Agency permissions set for {accountant.email}",
                )
            log_audit(
                request.user,
                None,
                "ACCOUNTANT_AGENCIES_SET",
                "User",
                accountant.id,
                old_values={"agency_assignments": old_values},
                new_values={"agency_assignments": new_values},
                description=f"Agency assignments replaced for {accountant.email}",
            )
        refreshed = self.get_queryset().get(pk=accountant.pk)
        return Response(AccountantSerializer(refreshed).data)

    @action(
        detail=True,
        methods=["post"],
        url_path="reset-password",
        throttle_classes=[ScopedRateThrottle],
        throttle_scope="password_reset",
    )
    def reset_password(self, request, pk=None):
        accountant = self.get_object()
        serializer = AccountantPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data["password"]
        try:
            validate_password(password, accountant)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)})
        accountant.set_password(password)
        accountant.save(update_fields=["password", "updated_at"])
        log_audit(
            request.user,
            None,
            "ACCOUNTANT_PASSWORD_RESET",
            "User",
            accountant.id,
            description=f"Password reset for {accountant.email}",
        )
        return Response({"detail": "Password reset successfully."})

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        accountant = self.get_object()
        old_active = accountant.is_active
        accountant.is_active = True
        accountant.save(update_fields=["is_active", "updated_at"])
        log_audit(request.user, None, "ACCOUNTANT_ACTIVATED", "User", accountant.id, {"is_active": old_active}, {"is_active": True}, f"Accountant activated: {accountant.email}")
        return Response(AccountantSerializer(accountant).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        accountant = self.get_object()
        old_active = accountant.is_active
        accountant.is_active = False
        accountant.save(update_fields=["is_active", "updated_at"])
        log_audit(request.user, None, "ACCOUNTANT_DEACTIVATED", "User", accountant.id, {"is_active": old_active}, {"is_active": False}, f"Accountant deactivated: {accountant.email}")
        return Response(AccountantSerializer(accountant).data)


class PersonViewSet(BaseSearchViewSet):
    serializer_class = PersonSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["full_name", "agency__name", "tpm_codes__code"]
    ordering_fields = ["full_name", "created_at"]

    def get_queryset(self):
        queryset = Person.objects.select_related("agency").prefetch_related("tpm_codes")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            pass
        else:
            queryset = queryset.filter(agency__user_assignments__user=self.request.user).distinct()
        agency = self.request.query_params.get("agency")
        active = self.request.query_params.get("active")
        if agency:
            queryset = queryset.filter(agency_id=agency)
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        from .terminal_register import lock_register
        lock_register()
        agency = serializer.validated_data["agency"]
        require_assignment_flag(self.request.user, agency, "can_create")
        person = serializer.save()
        log_audit(
            self.request.user,
            person.agency,
            "PERSON_CREATED",
            "Person",
            person.id,
            new_values={"full_name": person.full_name, "agent_type": person.agent_type, "is_active": person.is_active},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        from .terminal_register import lock_register
        lock_register()
        person = Person.objects.select_for_update().get(pk=self.get_object().pk)
        serializer.instance = person
        require_assignment_flag(self.request.user, person.agency, "can_edit")
        new_agency = serializer.validated_data.get("agency", person.agency)
        require_assignment_flag(self.request.user, new_agency, "can_edit")
        if new_agency.pk != person.agency_id and person.terminal_numbers.exists():
            raise ValidationError("This person has terminal records. Reassign those terminals before changing agency.")
        old_values = {"agency": person.agency_id, "full_name": person.full_name, "agent_type": person.agent_type, "is_active": person.is_active}
        updated = serializer.save()
        log_audit(
            self.request.user,
            updated.agency,
            "PERSON_UPDATED",
            "Person",
            updated.id,
            old_values=old_values,
            new_values={"agency": updated.agency_id, "full_name": updated.full_name, "agent_type": updated.agent_type, "is_active": updated.is_active},
        )

    def perform_destroy(self, instance):
        require_assignment_flag(self.request.user, instance.agency, "can_delete")
        old_active = instance.is_active
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        log_audit(
            self.request.user,
            instance.agency,
            "PERSON_DEACTIVATED",
            "Person",
            instance.id,
            old_values={"is_active": old_active},
            new_values={"is_active": False},
            description=f"Person deactivated: {instance.full_name}",
        )


class TPMCodeViewSet(BaseSearchViewSet):
    serializer_class = TPMCodeSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["code", "person__full_name", "person__agency__name"]
    ordering_fields = ["code", "created_at"]

    def get_queryset(self):
        queryset = TPMCode.objects.select_related("person", "person__agency")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            pass
        else:
            queryset = queryset.filter(person__agency__user_assignments__user=self.request.user).distinct()
        agency = self.request.query_params.get("agency")
        active = self.request.query_params.get("active")
        if agency:
            queryset = queryset.filter(person__agency_id=agency)
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    def save_code(self, serializer):
        try:
            with transaction.atomic():
                return serializer.save()
        except IntegrityError:
            # A concurrent request may have claimed the code after validation.
            serializer.validate_code(serializer.validated_data.get("code", serializer.instance.code if serializer.instance else ""))
            raise

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        from .terminal_register import lock_register
        lock_register()
        # Lock before DRF reads the instance so confirmation and audit use the current owner.
        TPMCode.objects.select_for_update().get(pk=self.get_object().pk)
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        person = serializer.validated_data["person"]
        require_assignment_flag(self.request.user, person.agency, "can_create")
        serializer.validated_data.pop("confirm_reassignment", None)
        code = self.save_code(serializer)
        log_audit(
            self.request.user,
            code.person.agency,
            "TPM_CODE_CREATED",
            "TPMCode",
            code.id,
            new_values={"person": code.person_id, "code": code.code, "is_active": code.is_active},
        )

    def perform_update(self, serializer):
        code = self.get_object()
        require_assignment_flag(self.request.user, code.person.agency, "can_edit")
        new_person = serializer.validated_data.get("person", code.person)
        require_assignment_flag(self.request.user, new_person.agency, "can_edit")
        if new_person.pk != code.person_id and code.terminal_numbers.exists():
            raise ValidationError("This Sub-Agent Number has terminal records. Use terminal reassignment before changing its owner.")
        confirmed = serializer.validated_data.pop("confirm_reassignment", False)
        if new_person.pk != code.person_id and not confirmed:
            raise ValidationError({"confirm_reassignment": "Confirm reassignment to a different person."})
        old_values = {"agency": code.person.agency_id, "person": code.person_id, "code": code.code, "is_active": code.is_active}
        updated = self.save_code(serializer)
        log_audit(
            self.request.user,
            updated.person.agency,
            "TPM_CODE_UPDATED",
            "TPMCode",
            updated.id,
            old_values=old_values,
            new_values={"agency": updated.person.agency_id, "person": updated.person_id, "code": updated.code, "is_active": updated.is_active},
        )

    def perform_destroy(self, instance):
        require_assignment_flag(self.request.user, instance.person.agency, "can_delete")
        old_active = instance.is_active
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        log_audit(
            self.request.user,
            instance.person.agency,
            "TPM_CODE_DEACTIVATED",
            "TPMCode",
            instance.id,
            old_values={"is_active": old_active},
            new_values={"is_active": False},
            description=f"Sub-Agent Number deactivated: {instance.code}",
        )


class PaymentPayerViewSet(PaymentQueryMixin, BaseSearchViewSet):
    pagination_class = PaymentPagination
    serializer_class = PaymentPayerSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["payer_name", "agency__name", "sub_agent_assignments__sub_agent_number__code"]
    ordering_fields = ["payer_name", "created_at", "is_active"]

    def get_queryset(self):
        expected_totals = PaymentObligation.objects.filter(payer_id=OuterRef("pk")).values("payer_id").annotate(total=Sum("total_expected")).values("total")
        collected_totals = PayerPayment.objects.filter(
            obligation__payer_id=OuterRef("pk"),
            status=PayerPayment.PaymentStatus.POSTED,
        ).values("obligation__payer_id").annotate(total=Sum("amount_received")).values("total")
        queryset = PaymentPayer.objects.select_related("agency", "created_by").annotate(
            _total_expected=Coalesce(
                Subquery(expected_totals, output_field=DecimalField(max_digits=14, decimal_places=2)),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ),
            _total_collected=Coalesce(
                Subquery(collected_totals, output_field=DecimalField(max_digits=14, decimal_places=2)),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ),
            _active_obligations=Count(
                "obligations",
                filter=~Q(obligations__status=PaymentObligation.ObligationStatus.CANCELLED),
                distinct=True,
            ),
        ).order_by("payer_name", "id")
        if self.request.user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(agency__user_assignments__user=self.request.user, agency__is_active=True).distinct()
        agency_ids = self.validate_agency_query()
        if agency_ids:
            queryset = queryset.filter(agency_id__in=agency_ids)
        active = self.request.query_params.get("active")
        if active and active not in {"true", "false"}:
            raise ValidationError({"active": "Use true or false."})
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    def perform_create(self, serializer):
        agency = serializer.validated_data["agency"]
        require_active_agency(agency)
        if self.request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(self.request.user, agency, "can_create")
        payer = serializer.save(created_by=self.request.user)
        log_audit(self.request.user, agency, AuditAction.PAYMENT_PAYER_CREATED, "PaymentPayer", payer.id, new_values={"agency_id": agency.id, "is_active": payer.is_active, "actor_id": self.request.user.id})

    def perform_update(self, serializer):
        payer = self.get_object()
        if self.request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(self.request.user, payer.agency, "can_edit")
        old_values = {"is_active": payer.is_active}
        payer = serializer.save()
        log_audit(self.request.user, payer.agency, AuditAction.PAYMENT_PAYER_UPDATED, "PaymentPayer", payer.id, old_values=old_values, new_values={"is_active": payer.is_active, "actor_id": self.request.user.id})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        payer = self.get_object()
        if request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(request.user, payer.agency, "can_delete")
        if not payer.is_active:
            return Response({"detail": "This payer is already inactive."}, status=409)
        payer.is_active = False
        payer.save(update_fields=["is_active", "updated_at"])
        log_audit(request.user, payer.agency, AuditAction.PAYMENT_PAYER_DEACTIVATED, "PaymentPayer", payer.id, old_values={"is_active": True}, new_values={"is_active": False, "actor_id": request.user.id})
        return Response(self.get_serializer(payer).data)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        payer = self.get_object()
        if request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(request.user, payer.agency, "can_edit")
        if payer.is_active:
            return Response({"detail": "This payer is already active."}, status=409)
        payer.is_active = True
        payer.save(update_fields=["is_active", "updated_at"])
        log_audit(request.user, payer.agency, AuditAction.PAYMENT_PAYER_REACTIVATED, "PaymentPayer", payer.id, old_values={"is_active": False}, new_values={"is_active": True, "actor_id": request.user.id})
        return Response(self.get_serializer(payer).data)

    @action(detail=True, methods=["post"])
    def assign_sub_agent(self, request, pk=None):
        payer = self.get_object()
        sub_agent_id = request.data.get("sub_agent_number")
        if not sub_agent_id:
            raise ValidationError({"sub_agent_number": "A Sub-Agent Number is required."})
        if request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(request.user, payer.agency, "can_edit")
        sub_agent = TPMCode.objects.select_related("person__agency").get(pk=sub_agent_id)
        if sub_agent.person.agency_id != payer.agency_id:
            raise ValidationError({"sub_agent_number": "Sub-Agent Number must belong to the same agency."})
        if not sub_agent.is_active or not sub_agent.person.is_active or not payer.agency.is_active:
            raise ValidationError({"sub_agent_number": "Inactive agency, person or Sub-Agent Number cannot be assigned."})
        with transaction.atomic():
            existing = PayerSubAgentAssignment.objects.select_for_update().filter(sub_agent_number=sub_agent, is_active=True).first()
            if existing and existing.payer_id != payer.id:
                raise ValidationError({"sub_agent_number": "This Sub-Agent Number already belongs to an active payer in this agency."})
            assignment, created = PayerSubAgentAssignment.objects.get_or_create(
                payer=payer,
                sub_agent_number=sub_agent,
                defaults={"assigned_by": request.user, "is_active": True},
            )
            if not created:
                assignment.is_active = True
                assignment.unassigned_by = None
                assignment.unassigned_at = None
                assignment.reassignment_reason = ""
                assignment.save(update_fields=["is_active", "unassigned_by", "unassigned_at", "reassignment_reason", "updated_at"])
            log_audit(request.user, payer.agency, AuditAction.PAYER_SUBAGENT_ASSIGNED, "PayerSubAgentAssignment", assignment.id, new_values={"payer_id": payer.id, "sub_agent_number_id": sub_agent.id, "actor_id": request.user.id})
        return Response(PayerSubAgentAssignmentSerializer(assignment).data)

    @action(detail=True, methods=["post"])
    def unassign_sub_agent(self, request, pk=None):
        payer = self.get_object()
        sub_agent_id = request.data.get("sub_agent_number")
        reason = request.data.get("reason", "")
        if not sub_agent_id:
            raise ValidationError({"sub_agent_number": "A Sub-Agent Number is required."})
        if request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(request.user, payer.agency, "can_edit")
        assignment = PayerSubAgentAssignment.objects.select_related("payer", "sub_agent_number").filter(payer=payer, sub_agent_number_id=sub_agent_id).first()
        if not assignment:
            raise ValidationError({"sub_agent_number": "This Sub-Agent Number is not linked to this payer."})
        if not assignment.is_active:
            return Response({"detail": "This assignment is already inactive."}, status=409)
        assignment.is_active = False
        assignment.unassigned_by = request.user
        assignment.unassigned_at = timezone.now()
        assignment.reassignment_reason = reason.strip()
        assignment.save(update_fields=["is_active", "unassigned_by", "unassigned_at", "reassignment_reason", "updated_at"])
        log_audit(request.user, payer.agency, AuditAction.PAYER_SUBAGENT_UNASSIGNED, "PayerSubAgentAssignment", assignment.id, new_values={"payer_id": payer.id, "sub_agent_number_id": assignment.sub_agent_number_id, "actor_id": request.user.id})
        return Response(PayerSubAgentAssignmentSerializer(assignment).data)

    @action(detail=True, methods=["post"])
    def reassign_sub_agent(self, request, pk=None):
        payer = self.get_object()
        if request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(request.user, payer.agency, "can_edit")
        if request.data.get("confirmed") is not True:
            raise ValidationError({"confirmed": "Explicit confirmation is required."})
        sub_agent_id = request.data.get("sub_agent_number")
        target_payer_id = request.data.get("new_payer") or request.data.get("new_payer_id")
        if not sub_agent_id or not target_payer_id:
            raise ValidationError({"sub_agent_number": "The Sub-Agent Number and new payer are required."})
        try:
            sub_agent_id = int(sub_agent_id)
            target_payer_id = int(target_payer_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"detail": "Sub-Agent Number and new payer must be numeric IDs."}) from exc
        if target_payer_id == payer.id:
            raise ValidationError({"new_payer": "The new payer must be different from the current payer."})
        with transaction.atomic():
            old_assignment = PayerSubAgentAssignment.objects.select_for_update().filter(payer=payer, sub_agent_number_id=sub_agent_id, is_active=True).first()
            if not old_assignment:
                raise ValidationError({"sub_agent_number": "This Sub-Agent Number is not actively linked to this payer."})
            target_payer = PaymentPayer.objects.select_for_update().filter(pk=target_payer_id).first()
            if not target_payer:
                raise ValidationError({"new_payer": "The target payer was not found."})
            if target_payer.agency_id != payer.agency_id:
                raise ValidationError({"new_payer": "Cross-agency reassignment is forbidden."})
            if not target_payer.is_active:
                raise ValidationError({"new_payer": "The target payer is inactive."})
            existing = PayerSubAgentAssignment.objects.select_for_update().filter(sub_agent_number_id=sub_agent_id, is_active=True).first()
            if existing and existing.payer_id != payer.id:
                raise ValidationError({"sub_agent_number": "This Sub-Agent Number is already assigned to another active payer."})
            old_assignment.is_active = False
            old_assignment.unassigned_by = request.user
            old_assignment.unassigned_at = timezone.now()
            old_assignment.reassignment_reason = "Reassigned"
            old_assignment.save(update_fields=["is_active", "unassigned_by", "unassigned_at", "reassignment_reason", "updated_at"])
            assignment, _ = PayerSubAgentAssignment.objects.get_or_create(
                payer=target_payer,
                sub_agent_number=old_assignment.sub_agent_number,
                defaults={"assigned_by": request.user, "is_active": True},
            )
            assignment.is_active = True
            assignment.assigned_by = request.user
            assignment.assigned_at = timezone.now()
            assignment.unassigned_by = None
            assignment.unassigned_at = None
            assignment.reassignment_reason = "Reassigned"
            assignment.save(update_fields=["is_active", "assigned_by", "assigned_at", "unassigned_by", "unassigned_at", "reassignment_reason", "updated_at"])
            log_audit(
                request.user,
                payer.agency,
                AuditAction.PAYER_SUBAGENT_REASSIGNED,
                "PayerSubAgentAssignment",
                assignment.id,
                old_values={"previous_payer_id": payer.id, "sub_agent_number_id": sub_agent_id},
                new_values={"new_payer_id": target_payer.id, "agency_id": payer.agency_id, "actor_id": request.user.id},
            )
        return Response(PayerSubAgentAssignmentSerializer(assignment).data)


class PaymentObligationViewSet(PaymentQueryMixin, BaseSearchViewSet):
    pagination_class = PaymentPagination
    serializer_class = PaymentObligationSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["obligation_number", "description", "payer__payer_name"]
    ordering_fields = ["obligation_date", "total_expected", "created_at", "status", "obligation_number"]

    def get_queryset(self):
        queryset = PaymentObligation.objects.select_related("agency", "payer", "payer__agency", "created_by").annotate(
            _posted_total=Coalesce(
                Sum("payments__amount_received", filter=Q(payments__status=PayerPayment.PaymentStatus.POSTED)),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ),
            _reversed_total=Coalesce(
                Sum("payments__amount_received", filter=Q(payments__status=PayerPayment.PaymentStatus.REVERSED)),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ),
        ).annotate(_balance=F("total_expected") - F("_posted_total")).order_by("-obligation_date", "-id")
        if self.request.user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(agency__user_assignments__user=self.request.user, agency__is_active=True).distinct()
        agency_ids = self.validate_agency_query()
        if agency_ids:
            queryset = queryset.filter(agency_id__in=agency_ids)
        payer = parse_single_id(self.request.query_params, "payer")
        status = self.request.query_params.get("status")
        if payer:
            queryset = queryset.filter(payer_id=payer)
        if status:
            if status not in PaymentObligation.ObligationStatus.values:
                raise ValidationError({"status": "Unsupported obligation status."})
            queryset = queryset.filter(status=status)
        description = self.request.query_params.get("description")
        if description:
            queryset = queryset.filter(description__icontains=description)
        obligation_number = self.request.query_params.get("obligation_number")
        if obligation_number:
            queryset = queryset.filter(obligation_number=obligation_number)
        start, end = validate_date_range(self.request.query_params, "obligation_start", "obligation_end")
        if start:
            queryset = queryset.filter(obligation_date__gte=start)
        if end:
            queryset = queryset.filter(obligation_date__lte=end)
        outstanding = self.request.query_params.get("outstanding_only")
        if outstanding and outstanding not in {"true", "false"}:
            raise ValidationError({"outstanding_only": "Use true or false."})
        if outstanding == "true":
            queryset = queryset.filter(status__in=[PaymentObligation.ObligationStatus.OPEN, PaymentObligation.ObligationStatus.PARTIALLY_PAID])
        return queryset

    def perform_create(self, serializer):
        payer = serializer.validated_data["payer"]
        agency = payer.agency
        if self.request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(self.request.user, agency, "can_create")
        obligation = serializer.save(agency=agency, created_by=self.request.user)
        log_audit(self.request.user, agency, AuditAction.PAYMENT_OBLIGATION_CREATED, "PaymentObligation", obligation.id, new_values={"agency_id": agency.id, "payer_id": payer.id, "obligation_number": obligation.obligation_number, "total_expected": str(obligation.total_expected), "status": obligation.status, "actor_id": self.request.user.id})

    def perform_update(self, serializer):
        obligation = self.get_object()
        if self.request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(self.request.user, obligation.agency, "can_edit")
        has_posted = obligation.payments.filter(status=PayerPayment.PaymentStatus.POSTED).exists()
        if has_posted:
            for field in ("agency", "payer", "total_expected"):
                if field in serializer.validated_data:
                    raise ValidationError({field: f"{field.replace('_', ' ').title()} cannot change after the first posted payment."})
        old_values = {"obligation_date": obligation.obligation_date.isoformat(), "total_expected": str(obligation.total_expected), "status": obligation.status}
        updated = serializer.save()
        log_audit(self.request.user, updated.agency, AuditAction.PAYMENT_OBLIGATION_UPDATED, "PaymentObligation", updated.id, old_values=old_values, new_values={"obligation_date": updated.obligation_date.isoformat(), "total_expected": str(updated.total_expected), "status": updated.status, "actor_id": self.request.user.id})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        obligation = self.get_object()
        if request.user.role != UserRole.SUPER_ADMIN:
            require_assignment_flag(request.user, obligation.agency, "can_delete")
        reason = request.data.get("reason", "")
        if not reason.strip():
            raise ValidationError({"reason": "A cancellation reason is required."})
        with transaction.atomic():
            obligation = PaymentObligation.objects.select_for_update().get(pk=obligation.pk)
            if obligation.payments.filter(status=PayerPayment.PaymentStatus.POSTED).exists():
                raise ValidationError({"detail": "This obligation has posted payments. Reverse those payments before cancelling."})
            obligation.status = PaymentObligation.ObligationStatus.CANCELLED
            obligation.cancelled_by = request.user
            obligation.cancelled_at = timezone.now()
            obligation.cancellation_reason = reason.strip()
            obligation.save(update_fields=["status", "cancelled_by", "cancelled_at", "cancellation_reason", "updated_at"])
        log_audit(request.user, obligation.agency, AuditAction.PAYMENT_OBLIGATION_CANCELLED, "PaymentObligation", obligation.id, new_values={"status": obligation.status, "actor_id": request.user.id})
        return Response(self.get_serializer(obligation).data)


class PayerPaymentViewSet(PaymentQueryMixin, BaseSearchViewSet):
    pagination_class = PaymentPagination
    serializer_class = PayerPaymentSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["receipt_number", "payer_name_snapshot", "obligation__obligation_number", "obligation__description"]
    ordering_fields = ["payment_date", "amount_received", "receipt_number", "status", "payment_method"]

    def get_queryset(self):
        queryset = PayerPayment.objects.select_related("obligation", "recorded_by", "obligation__payer", "obligation__agency").order_by("-payment_date", "-id")
        if self.request.user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(obligation__agency__user_assignments__user=self.request.user, obligation__agency__is_active=True).distinct()
        agency_ids = self.validate_agency_query()
        if agency_ids:
            queryset = queryset.filter(obligation__agency_id__in=agency_ids)
        payer = parse_single_id(self.request.query_params, "payer")
        obligation = parse_single_id(self.request.query_params, "obligation")
        status = self.request.query_params.get("status")
        if payer:
            queryset = queryset.filter(obligation__payer_id=payer)
        if obligation:
            queryset = queryset.filter(obligation_id=obligation)
        if status:
            if status not in PayerPayment.PaymentStatus.values:
                raise ValidationError({"status": "Unsupported payment status."})
            queryset = queryset.filter(status=status)
        payment_method = self.request.query_params.get("payment_method")
        if payment_method:
            if payment_method not in PayerPayment.PaymentMethod.values:
                raise ValidationError({"payment_method": "Unsupported payment method."})
            queryset = queryset.filter(payment_method=payment_method)
        receipt_number = self.request.query_params.get("receipt_number")
        if receipt_number:
            queryset = queryset.filter(receipt_number=receipt_number)
        start, end = validate_date_range(self.request.query_params, "payment_start", "payment_end")
        if start:
            queryset = queryset.filter(payment_date__date__gte=start)
        if end:
            queryset = queryset.filter(payment_date__date__lte=end)
        recorder = parse_single_id(self.request.query_params, "recorded_by")
        if recorder is not None:
            if self.request.user.role != UserRole.SUPER_ADMIN:
                raise PermissionDenied("Only Super Admin can filter by recorder.")
            queryset = queryset.filter(recorded_by_id=recorder)
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            obligation = serializer.validated_data["obligation"]
            obligation_locked = PaymentObligation.objects.select_for_update().select_related("agency", "payer").get(pk=obligation.pk)
            if self.request.user.role != UserRole.SUPER_ADMIN:
                require_assignment_flag(self.request.user, obligation_locked.agency, "can_create")
            key = serializer.validated_data["idempotency_key"].strip()
            existing = PayerPayment.objects.filter(idempotency_key=key).first()
            if existing:
                same_request = (
                    existing.obligation_id == obligation_locked.id
                    and existing.amount_received == serializer.validated_data["amount_received"]
                    and existing.payment_method == serializer.validated_data["payment_method"]
                    and existing.payment_reference == serializer.validated_data.get("payment_reference", "")
                    and existing.notes == serializer.validated_data.get("notes", "")
                )
                if not same_request:
                    raise ValidationError({"idempotency_key": "This idempotency key was already used for different payment data."})
                self._idempotent_payment = existing
                return
            if obligation_locked.status in {PaymentObligation.ObligationStatus.CANCELLED, PaymentObligation.ObligationStatus.PAID}:
                raise ValidationError({"obligation": "Only open obligations with an outstanding balance accept payments."})
            current_totals = obligation_locked.payments.filter(status=PayerPayment.PaymentStatus.POSTED).aggregate(total=Sum("amount_received"))
            total_paid = money(current_totals["total"] or Decimal("0.00"))
            balance = money(obligation_locked.total_expected - total_paid)
            amount = serializer.validated_data["amount_received"]
            if amount > balance:
                raise ValidationError({"amount_received": "Payment exceeds the current outstanding balance."})
            if amount <= 0:
                raise ValidationError({"amount_received": "Payment amount must be greater than zero."})
            payment = serializer.save(
                agency_snapshot=obligation_locked.agency.name,
                payer_name_snapshot=obligation_locked.payer.payer_name,
                linked_sub_agent_numbers_snapshot=list(obligation_locked.payer.sub_agent_assignments.filter(is_active=True).values_list("sub_agent_number__code", flat=True)),
                obligation_number_snapshot=obligation_locked.obligation_number,
                obligation_description_snapshot=obligation_locked.description,
                obligation_date_snapshot=obligation_locked.obligation_date,
                expected_amount_snapshot=obligation_locked.total_expected,
                amount_previously_paid=total_paid,
                cumulative_amount_paid=money(total_paid + amount),
                balance_after_payment=money(balance - amount),
                payment_date=timezone.now(),
                recorded_by=self.request.user,
                recorded_by_display_snapshot=self.request.user.full_name or self.request.user.email,
            )
            obligation_locked.refresh_status(); obligation_locked.save(update_fields=["status", "updated_at"])
            log_audit(self.request.user, obligation_locked.agency, AuditAction.PAYMENT_RECORDED, "PayerPayment", payment.id, new_values={"receipt_number": payment.receipt_number, "amount_received": str(payment.amount_received), "obligation_id": obligation_locked.id, "status": payment.status, "actor_id": self.request.user.id})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._idempotent_payment = None
        self.perform_create(serializer)
        payment = self._idempotent_payment or serializer.instance
        headers = self.get_success_headers(self.get_serializer(payment).data)
        return Response(self.get_serializer(payment).data, status=status.HTTP_200_OK if self._idempotent_payment else status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Payment records cannot be updated."})

    def partial_update(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Payment records cannot be updated."})

    def destroy(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Payment records cannot be deleted."})

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payment = self.get_object()
        if request.user.role != UserRole.SUPER_ADMIN:
            raise PermissionDenied("Only Super Admin can reverse posted payments.")
        reason = request.data.get("reason", "")
        if not reason.strip():
            raise ValidationError({"reason": "A reversal reason is required."})
        if request.data.get("confirmed") is not True:
            raise ValidationError({"confirmed": "Explicit confirmation is required."})
        with transaction.atomic():
            payment_locked = PayerPayment.objects.select_for_update().select_related("obligation").get(pk=payment.pk)
            obligation_locked = PaymentObligation.objects.select_for_update().get(pk=payment_locked.obligation_id)
            if payment_locked.status == PayerPayment.PaymentStatus.REVERSED:
                return Response({"detail": "This payment has already been reversed."}, status=409)
            if payment_locked.status != PayerPayment.PaymentStatus.POSTED:
                raise ValidationError({"detail": "Only posted payments can be reversed."})
            payment_locked.status = PayerPayment.PaymentStatus.REVERSED
            payment_locked.reversed_by = request.user
            payment_locked.reversed_at = timezone.now()
            payment_locked.reversal_reason = reason.strip()
            payment_locked.save(update_fields=["status", "reversed_by", "reversed_at", "reversal_reason", "updated_at"])
            obligation_locked.refresh_status(); obligation_locked.save(update_fields=["status", "updated_at"])
            log_audit(request.user, obligation_locked.agency, AuditAction.PAYMENT_REVERSED, "PayerPayment", payment_locked.id, new_values={"receipt_number": payment_locked.receipt_number, "status": payment_locked.status, "actor_id": request.user.id})
        return Response(self.get_serializer(payment_locked).data)

    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        payment = self.get_object()
        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, pageCompression=0)
        styles = getSampleStyleSheet()
        story = [Paragraph("Treasureland Investment Limited", styles["Title"]), Paragraph(f"Receipt: {payment.receipt_number}", styles["Heading2"]), Spacer(1, 6)]
        if payment.status == PayerPayment.PaymentStatus.REVERSED:
            story.append(Paragraph("REVERSED", styles["Heading1"]))
        rows = [
            ("Status", payment.status), ("Payment date/time", payment.payment_date.isoformat()),
            ("Agency", payment.agency_snapshot), ("Payer", payment.payer_name_snapshot),
            ("Linked Sub-Agent Numbers", ", ".join(payment.linked_sub_agent_numbers_snapshot) or "None"),
            ("Obligation", f"{payment.obligation_number_snapshot} - {payment.obligation_description_snapshot}"),
            ("Obligation date", payment.obligation_date_snapshot.isoformat()),
            ("Expected amount", str(payment.expected_amount_snapshot)), ("Previously paid", str(payment.amount_previously_paid)),
            ("Amount received", str(payment.amount_received)), ("Cumulative paid", str(payment.cumulative_amount_paid)),
            ("Outstanding balance", str(payment.balance_after_payment)), ("Payment method", payment.get_payment_method_display()),
            ("Payment reference", payment.payment_reference or "None"), ("Recorded by", payment.recorded_by_display_snapshot),
            ("Notes", payment.notes or "None"),
        ]
        table = Table(rows, colWidths=[48 * mm, 125 * mm])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")]))
        story.append(table)
        document.build(story)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{get_valid_filename(payment.receipt_number)}.pdf"'
        return response


class PaymentAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        agency_ids = parse_id_filter(request.query_params, "agency")
        ensure_agency_filter_access(request.user, agency_ids)
        obligations = PaymentObligation.objects.all()
        if request.user.role != UserRole.SUPER_ADMIN:
            obligations = obligations.filter(agency__user_assignments__user=request.user, agency__is_active=True).distinct()
        if agency_ids:
            obligations = obligations.filter(agency_id__in=agency_ids)

        payer_id = parse_single_id(request.query_params, "payer")
        if payer_id:
            obligations = obligations.filter(payer_id=payer_id)
        obligation_status = request.query_params.get("obligation_status")
        if obligation_status:
            if obligation_status not in PaymentObligation.ObligationStatus.values:
                raise ValidationError({"obligation_status": "Unsupported obligation status."})
            obligations = obligations.filter(status=obligation_status)
        obligation_start, obligation_end = validate_date_range(request.query_params, "obligation_start", "obligation_end")
        if obligation_start:
            obligations = obligations.filter(obligation_date__gte=obligation_start)
        if obligation_end:
            obligations = obligations.filter(obligation_date__lte=obligation_end)

        payments = PayerPayment.objects.filter(obligation__in=obligations)
        payment_start, payment_end = validate_date_range(request.query_params, "payment_start", "payment_end")
        if payment_start:
            payments = payments.filter(payment_date__date__gte=payment_start)
        if payment_end:
            payments = payments.filter(payment_date__date__lte=payment_end)
        payment_method = request.query_params.get("payment_method")
        if payment_method:
            if payment_method not in PayerPayment.PaymentMethod.values:
                raise ValidationError({"payment_method": "Unsupported payment method."})
            payments = payments.filter(payment_method=payment_method)
        recorder = parse_single_id(request.query_params, "recorded_by")
        if recorder is not None:
            if request.user.role != UserRole.SUPER_ADMIN:
                raise PermissionDenied("Only Super Admin can filter by recorder.")
            payments = payments.filter(recorded_by_id=recorder)

        posted_payments = payments.filter(status=PayerPayment.PaymentStatus.POSTED)
        reversed_payments = payments.filter(status=PayerPayment.PaymentStatus.REVERSED)
        zero = Decimal("0.00")
        total_expected = obligations.aggregate(total=Sum("total_expected"))["total"] or zero
        posted_total = posted_payments.aggregate(total=Sum("amount_received"))["total"] or zero
        reversed_total = reversed_payments.aggregate(total=Sum("amount_received"))["total"] or zero
        gross_posted_total = payments.aggregate(total=Sum("amount_received"))["total"] or zero
        outstanding_obligations = obligations.filter(status__in=[PaymentObligation.ObligationStatus.OPEN, PaymentObligation.ObligationStatus.PARTIALLY_PAID])
        outstanding_expected = outstanding_obligations.aggregate(total=Sum("total_expected"))["total"] or zero
        outstanding_posted = PayerPayment.objects.filter(
            obligation__in=outstanding_obligations,
            status=PayerPayment.PaymentStatus.POSTED,
        ).aggregate(total=Sum("amount_received"))["total"] or zero
        total_outstanding = money(outstanding_expected - outstanding_posted)
        collection_rate = money((posted_total / total_expected) * Decimal("100")) if total_expected else zero

        status_rows = {row["status"]: row["count"] for row in obligations.values("status").annotate(count=Count("id"))}
        by_status = {
            status_value: status_rows.get(status_value, 0)
            for status_value, _ in PaymentObligation.ObligationStatus.choices
        }
        by_method = {}
        method_rows = {
            row["payment_method"]: row
            for row in payments.values("payment_method").annotate(
                posted_amount=Sum("amount_received", filter=Q(status=PayerPayment.PaymentStatus.POSTED)),
                reversed_amount=Sum("amount_received", filter=Q(status=PayerPayment.PaymentStatus.REVERSED)),
                posted_count=Count("id", filter=Q(status=PayerPayment.PaymentStatus.POSTED)),
                reversed_count=Count("id", filter=Q(status=PayerPayment.PaymentStatus.REVERSED)),
            )
        }
        for method_value, method_label in PayerPayment.PaymentMethod.choices:
            method_row = method_rows.get(method_value, {})
            method_posted = (method_row.get("posted_amount") or zero) + (method_row.get("reversed_amount") or zero)
            method_reversed = method_row.get("reversed_amount") or zero
            by_method[method_value] = {
                "label": method_label,
                "gross_posted_amount": str(money(method_posted)),
                "reversed_amount": str(money(method_reversed)),
                "net_collected_amount": str(money(method_posted - method_reversed)),
                "posted_receipt_count": method_row.get("posted_count", 0),
                "reversed_receipt_count": method_row.get("reversed_count", 0),
            }

        trend_rows = list(payments.values("payment_date", "amount_received", "status"))
        trend_start = payment_start or (min((row["payment_date"].date() for row in trend_rows), default=None))
        trend_end = payment_end or (max((row["payment_date"].date() for row in trend_rows), default=None))
        trends = []
        grouping = "daily"
        if trend_start and trend_end:
            grouping = "daily" if (trend_end - trend_start).days <= 92 else "monthly"
            totals = {}
            for row in trend_rows:
                period = row["payment_date"].date()
                if grouping == "monthly":
                    period = period.replace(day=1)
                bucket = totals.setdefault(period, {"gross_posted_amount": zero, "reversed_amount": zero})
                bucket["gross_posted_amount"] += row["amount_received"]
                if row["status"] == PayerPayment.PaymentStatus.REVERSED:
                    bucket["reversed_amount"] += row["amount_received"]
            cursor = trend_start if grouping == "daily" else trend_start.replace(day=1)
            final_period = trend_end if grouping == "daily" else trend_end.replace(day=1)
            while cursor <= final_period:
                bucket = totals.get(cursor, {"gross_posted_amount": zero, "reversed_amount": zero})
                trends.append({
                    "period": cursor.isoformat(),
                    "gross_posted_amount": str(money(bucket["gross_posted_amount"])),
                    "reversed_amount": str(money(bucket["reversed_amount"])),
                    "net_collected_amount": str(money(bucket["gross_posted_amount"] - bucket["reversed_amount"])),
                })
                if grouping == "daily":
                    cursor += timedelta(days=1)
                elif cursor.month == 12:
                    cursor = cursor.replace(year=cursor.year + 1, month=1)
                else:
                    cursor = cursor.replace(month=cursor.month + 1)

        response = {
            "obligation_portfolio": {
                "total_expected": str(money(total_expected)),
                "total_posted": str(money(posted_total)),
                "total_outstanding": str(total_outstanding),
                "collection_rate": str(collection_rate),
                "obligation_count": obligations.count(),
                "status_counts": by_status,
            },
            "collections": {
                "gross_posted_amount": str(money(gross_posted_total)),
                "reversed_amount": str(money(reversed_total)),
                "net_collected_amount": str(money(gross_posted_total - reversed_total)),
                "posted_receipt_count": posted_payments.count(),
                "reversed_receipt_count": reversed_payments.count(),
                "by_payment_method": by_method,
            },
            "trends": {"grouping": grouping, "periods": trends},
        }
        if request.user.role == UserRole.SUPER_ADMIN:
            agency_rows = list(obligations.values("agency_id", "agency__name").annotate(
                expected=Sum("total_expected"),
                outstanding_expected=Sum("total_expected", filter=Q(status__in=[PaymentObligation.ObligationStatus.OPEN, PaymentObligation.ObligationStatus.PARTIALLY_PAID])),
                obligation_count=Count("id"),
            ).order_by("agency__name"))
            agency_payment_rows = {
                row["obligation__agency_id"]: row
                for row in payments.values("obligation__agency_id").annotate(
                    posted=Sum("amount_received", filter=Q(status=PayerPayment.PaymentStatus.POSTED)),
                    reversed=Sum("amount_received", filter=Q(status=PayerPayment.PaymentStatus.REVERSED)),
                    posted_receipt_count=Count("id", filter=Q(status=PayerPayment.PaymentStatus.POSTED)),
                )
            }
            response["agency_breakdown"] = []
            for row in agency_rows:
                payment_row = agency_payment_rows.get(row["agency_id"], {})
                posted = payment_row.get("posted") or zero
                reversed_amount = payment_row.get("reversed") or zero
                gross = posted + reversed_amount
                expected = row["expected"] or zero
                response["agency_breakdown"].append({
                    "agency_id": row["agency_id"],
                    "agency_name": row["agency__name"],
                    "expected": str(money(expected)),
                    "net_collected": str(money(gross - reversed_amount)),
                    "outstanding": str(money((row["outstanding_expected"] or zero) - posted)),
                    "collection_rate": str(money((posted / expected * Decimal("100")) if expected else zero)),
                    "obligation_count": row["obligation_count"],
                    "posted_receipt_count": payment_row.get("posted_receipt_count", 0),
                })
        return Response(response)


class GameViewSet(BaseSearchViewSet):
    serializer_class = GameSerializer
    permission_classes = [SuperAdminOnlyWrites]
    queryset = Game.objects.all()
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    @action(detail=False, methods=["get"], url_path="for-date")
    def for_date(self, request):
        date_text = request.query_params.get("date")
        if not date_text:
            raise ValidationError({"date": "date=YYYY-MM-DD is required."})
        try:
            selected_date = timezone.datetime.fromisoformat(date_text).date()
        except ValueError as exc:
            raise ValidationError({"date": "Use YYYY-MM-DD."}) from exc
        schedules = WeeklyGameSchedule.objects.select_related("game").filter(
            weekday=selected_date.isoweekday(),
            is_active=True,
            game__is_active=True,
        ).order_by("display_order", "id")
        return Response(WeeklyGameScheduleSerializer(schedules, many=True).data)


class WeeklyGameScheduleViewSet(BaseSearchViewSet):
    serializer_class = WeeklyGameScheduleSerializer
    permission_classes = [SuperAdminOnlyWrites]
    queryset = WeeklyGameSchedule.objects.select_related("game")
    search_fields = ["game__name"]
    ordering_fields = ["weekday", "display_order", "closing_time"]

    def get_queryset(self):
        queryset = WeeklyGameSchedule.objects.select_related("game").order_by("weekday", "display_order", "id")
        active = self.request.query_params.get("active")
        weekday = self.request.query_params.get("weekday")
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        if weekday:
            if not weekday.isdigit() or int(weekday) not in range(1, 8):
                raise ValidationError({"weekday": "Use a valid weekday value from 1 to 7."})
            queryset = queryset.filter(weekday=int(weekday))
        return queryset

    def _values_for_audit(self, schedule):
        return {
            "game": schedule.game_id,
            "game_name": schedule.game.name,
            "weekday": schedule.weekday,
            "is_whole_day": schedule.is_whole_day,
            "closing_time": schedule.closing_time,
            "draw_time": schedule.draw_time,
            "display_order": schedule.display_order,
            "is_active": schedule.is_active,
        }

    def perform_create(self, serializer):
        schedule = serializer.save()
        log_audit(
            self.request.user,
            None,
            AuditAction.SCHEDULE_CREATED,
            "WeeklyGameSchedule",
            schedule.id,
            new_values=self._values_for_audit(schedule),
            description=f"Schedule created: {schedule.game.name} on {schedule.get_weekday_display()}",
        )

    def perform_update(self, serializer):
        schedule = self.get_object()
        old_values = self._values_for_audit(schedule)
        updated = serializer.save()
        action = AuditAction.SCHEDULE_UPDATED
        if old_values["is_active"] is False and updated.is_active is True:
            action = AuditAction.SCHEDULE_ACTIVATED
        elif old_values["is_active"] is True and updated.is_active is False:
            action = AuditAction.SCHEDULE_DEACTIVATED
        log_audit(
            self.request.user,
            None,
            action,
            "WeeklyGameSchedule",
            updated.id,
            old_values=old_values,
            new_values=self._values_for_audit(updated),
            description=f"Schedule updated: {updated.game.name} on {updated.get_weekday_display()}",
        )

    def perform_destroy(self, instance):
        old_values = self._values_for_audit(instance)
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        log_audit(
            self.request.user,
            None,
            AuditAction.SCHEDULE_DEACTIVATED,
            "WeeklyGameSchedule",
            instance.id,
            old_values=old_values,
            new_values=self._values_for_audit(instance),
            description=f"Schedule deactivated: {instance.game.name} on {instance.get_weekday_display()}",
        )


class DailySheetImportBatchViewSet(AgencyWriteLockMixin, viewsets.GenericViewSet):
    serializer_class = DailySheetImportBatchSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        queryset = DailySheetImportBatch.objects.select_related("uploader", "agency", "existing_sheet", "confirmed_sheet")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(uploader=self.request.user)

    def _metadata(self, batch):
        return {
            "agency": batch.agency_id,
            "transaction_date": batch.transaction_date,
            "file_name": batch.original_filename,
            "file_hash": batch.file_hash,
            "status": batch.status,
            "valid_row_count": batch.preview_payload.get("valid_row_count", 0),
            "ignored_blank_rows": batch.preview_payload.get("ignored_blank_rows", 0),
            "ignored_zero_rows": batch.preview_payload.get("ignored_zero_rows", 0),
            "warning_count": len(batch.warnings or []),
            "error_count": len(batch.errors or []),
            "existing_sheet": batch.existing_sheet_id,
            "existing_transaction_count": batch.existing_transaction_count,
        }

    def _current_schedule_snapshot(self, transaction_date):
        schedules = (
            WeeklyGameSchedule.objects.select_for_update()
            .select_related("game")
            .filter(weekday=transaction_date.isoweekday(), is_active=True, game__is_active=True)
            .order_by("display_order", "id")
        )
        return [
            {
                "game_name": schedule.game.name,
                "is_whole_day": schedule.is_whole_day,
                "closing_time": schedule.closing_time.isoformat() if schedule.closing_time else None,
                "draw_time": schedule.draw_time.isoformat() if schedule.draw_time else None,
                "display_order": schedule.display_order,
            }
            for schedule in schedules
        ]

    def _sheet_schedule_snapshot(self, sheet):
        return [
            {
                "game_name": game.game_name_snapshot,
                "is_whole_day": game.is_whole_day_snapshot,
                "closing_time": game.closing_time_snapshot.isoformat() if game.closing_time_snapshot else None,
                "draw_time": game.draw_time_snapshot.isoformat() if game.draw_time_snapshot else None,
                "display_order": game.display_order,
            }
            for game in sheet.sheet_games.select_for_update().order_by("display_order", "id")
        ]

    def _agency_from_request(self, request):
        request_data = request.query_params if request.method == "GET" else request.data
        agency_id = request_data.get("agency")
        if not str(agency_id or "").isdigit():
            raise ValidationError({"agency": "Select a valid agency."})
        try:
            agency = Agency.objects.get(pk=int(agency_id), is_active=True)
        except Agency.DoesNotExist as exc:
            raise ValidationError({"agency": "Select an active agency."}) from exc
        require_assignment_flag(request.user, agency, "can_create")
        return agency

    @action(detail=False, methods=["get"], url_path="template")
    def template(self, request):
        agency = self._agency_from_request(request)
        date_text = request.query_params.get("transaction_date")
        try:
            selected_date = timezone.datetime.fromisoformat(str(date_text)).date()
        except (TypeError, ValueError) as exc:
            raise ValidationError({"transaction_date": "Use YYYY-MM-DD."}) from exc
        workbook = build_daily_sheet_template(agency, selected_date)
        buffer = BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="daily-sheet-template-{selected_date.isoformat()}.xlsx"'
        return response

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        agency = self._agency_from_request(request)
        date_text = request.data.get("transaction_date")
        try:
            selected_date = timezone.datetime.fromisoformat(str(date_text)).date()
        except (TypeError, ValueError) as exc:
            raise ValidationError({"transaction_date": "Use YYYY-MM-DD."}) from exc
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            raise ValidationError({"file": "Upload one .xlsx workbook."})
        try:
            parsed = parse_daily_sheet_workbook(uploaded_file, agency, selected_date)
        except DjangoValidationError as exc:
            batch = DailySheetImportBatch.objects.create(
                uploader=request.user,
                agency=agency,
                transaction_date=selected_date,
                original_filename=get_valid_filename(getattr(uploaded_file, "name", "upload.xlsx"))[:255],
                file_hash="",
                status=DailySheetImportStatus.FAILED,
                preview_payload={},
                warnings=[],
                errors=[{"message": str(exc.messages[0] if hasattr(exc, "messages") else exc)}],
                expires_at=timezone.now() + timedelta(hours=2),
            )
            log_audit(request.user, agency, AuditAction.IMPORT_FAILED, "DailySheetImportBatch", batch.id, new_values=self._metadata(batch), description="Daily sheet import preview failed.")
            return Response(self.get_serializer(batch).data, status=status.HTTP_400_BAD_REQUEST)

        existing_sheet = None
        if parsed.payload.get("existing_sheet"):
            existing_sheet = DailySheet.objects.get(pk=parsed.payload["existing_sheet"])
        batch = DailySheetImportBatch.objects.create(
            uploader=request.user,
            agency=agency,
            transaction_date=selected_date,
            original_filename=parsed.payload["file_name"],
            file_hash=parsed.payload["file_hash"],
            status=DailySheetImportStatus.PREVIEWED,
            preview_payload=parsed.payload,
            warnings=parsed.warnings,
            errors=parsed.errors,
            existing_sheet=existing_sheet,
            existing_transaction_count=parsed.payload["existing_transaction_count"],
            expires_at=timezone.now() + timedelta(hours=2),
        )
        log_audit(request.user, agency, AuditAction.IMPORT_PREVIEWED, "DailySheetImportBatch", batch.id, new_values=self._metadata(batch), description="Daily sheet import previewed.")
        return Response(self.get_serializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        try:
            return self._confirm_locked(request, pk)
        except (APIException, Http404):
            raise
        except IntegrityError as exc:
            reference = log_import_confirmation_error(exc, logging.WARNING)
            return Response(
                {"detail": f"The import could not be confirmed because the target data changed. Create a fresh preview. Reference: {reference}"},
                status=status.HTTP_409_CONFLICT,
            )
        except Exception as exc:
            reference = log_import_confirmation_error(exc, logging.ERROR)
            self.get_queryset().filter(pk=pk, status=DailySheetImportStatus.PREVIEWED).update(
                status=DailySheetImportStatus.FAILED,
                errors=[{"message": "Confirmation failed.", "reference": reference}],
                updated_at=timezone.now(),
            )
            return Response(
                {"detail": f"The import could not be confirmed. No transactions were written. Reference: {reference}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _confirm_locked(self, request, pk=None):
        batch = self.get_object()
        require_assignment_flag(request.user, batch.agency, "can_create")
        replace_existing = request.data.get("replace_existing") is True
        acknowledge_date_mismatch = request.data.get("acknowledge_date_mismatch") is True

        with transaction.atomic():
            from .terminal_register import lock_register
            lock_register()
            # Nullable sheet joins cannot be locked by PostgreSQL. Lock the batch;
            # the target sheet and its game snapshots are locked explicitly below.
            batch = self.get_queryset().select_for_update(of=("self",)).get(pk=batch.pk)
            require_assignment_flag(request.user, batch.agency, "can_create")
            if batch.status != DailySheetImportStatus.PREVIEWED:
                raise ValidationError({"status": "Only previewed imports can be confirmed."})
            if batch.is_expired:
                batch.status = DailySheetImportStatus.EXPIRED
                batch.save(update_fields=["status", "updated_at"])
                raise ValidationError({"status": "Import preview expired. Upload the workbook again."})
            if batch.errors:
                raise ValidationError({"errors": "Resolve blocking errors before confirming."})
            if batch.preview_payload.get("requires_date_mismatch_ack") and not acknowledge_date_mismatch:
                raise ValidationError({"acknowledge_date_mismatch": "Confirm the workbook date mismatch before importing."})

            current_sheet = DailySheet.objects.select_for_update().filter(agency=batch.agency, transaction_date=batch.transaction_date).first()
            preview_sheet_id = batch.preview_payload.get("existing_sheet")
            if (current_sheet.id if current_sheet else None) != preview_sheet_id:
                raise ValidationError({"daily_sheet": "Target daily sheet changed after preview. Create a fresh preview."})
            if current_sheet:
                if not current_sheet.is_accountant_editable:
                    raise ValidationError({"daily_sheet": "Submitted or approved sheets cannot be overwritten."})
                if self._sheet_schedule_snapshot(current_sheet) != batch.preview_payload.get("schedule_snapshot", []):
                    raise ValidationError({"daily_sheet": "Daily sheet game snapshots changed after preview. Create a fresh preview."})
                current_count = current_sheet.transactions.select_for_update().count()
                if current_count != batch.existing_transaction_count:
                    raise ValidationError({"daily_sheet": "Daily sheet transactions changed after preview. Create a fresh preview."})
                if current_count and not replace_existing:
                    raise ValidationError({"replace_existing": "Set replace_existing=true to replace existing transactions."})
                sheet = current_sheet
                sheet.transactions.all().delete()
            else:
                current_schedule = self._current_schedule_snapshot(batch.transaction_date)
                if current_schedule != batch.preview_payload.get("schedule_snapshot", []):
                    raise ValidationError({"daily_sheet": "The selected date schedule changed after preview. Create a fresh preview."})
                sheet = DailySheet.objects.create(agency=batch.agency, transaction_date=batch.transaction_date, created_by=request.user)
                sheet.copy_weekday_games()

            sheet_games = {game.game_name_snapshot.lower(): game for game in sheet.sheet_games.select_for_update().order_by("display_order", "id")}
            created_transactions = []
            for row in batch.preview_payload.get("rows", []):
                try:
                    tpm_code = TPMCode.objects.select_for_update().select_related("person").get(
                        pk=row["tpm_code_id"],
                        person__agency=batch.agency,
                        person__is_active=True,
                        is_active=True,
                    )
                except TPMCode.DoesNotExist as exc:
                    raise ValidationError({"tpm_code": "A Sub-Agent Number changed after preview. Create a fresh preview."}) from exc
                if tpm_code.code != row["tpm_code"] or tpm_code.person.full_name != row["person_name"] or ("person_id" in row and tpm_code.person_id != row["person_id"]):
                    raise ValidationError("Sub-Agent identity changed after preview. Create a fresh preview.")
                from .models import TerminalNumber
                current_terminal = TerminalNumber.objects.filter(sub_agent_number=tpm_code, is_active=True).values_list("terminal_number", flat=True).first() or ""
                if row.get("terminal_number") and current_terminal != row["terminal_number"]:
                    raise ValidationError("Terminal assignment changed after preview. Create a fresh preview.")
                txn = TPMDailyTransaction(
                    daily_sheet=sheet,
                    tpm_code=tpm_code,
                    created_by=request.user,
                    updated_by=request.user,
                )
                txn.save(terminal_snapshot=row.get("terminal_number"))
                created_transactions.append(txn)
                TransactionGameSale.objects.bulk_create(
                    [
                        TransactionGameSale(
                            transaction=txn,
                            daily_sheet_game=sheet_game,
                            amount=money(Decimal(row["amounts"].get(sheet_game.game_name_snapshot, "0.00"))),
                        )
                        for sheet_game in sheet_games.values()
                    ]
                )

            batch.status = DailySheetImportStatus.CONFIRMED
            batch.confirmed_sheet = sheet
            batch.confirmed_at = timezone.now()
            batch.save(update_fields=["status", "confirmed_sheet", "confirmed_at", "updated_at"])
            log_audit(request.user, batch.agency, AuditAction.IMPORT_CONFIRMED, "DailySheetImportBatch", batch.id, new_values=self._metadata(batch), description="Daily sheet import confirmed.", daily_sheet=sheet)
        return Response({"daily_sheet": sheet.id, "imported_rows": len(created_transactions)})

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        batch = self.get_object()
        require_assignment_flag(request.user, batch.agency, "can_create")
        if batch.status != DailySheetImportStatus.PREVIEWED:
            raise ValidationError({"status": "Only previewed imports can be cancelled."})
        batch.status = DailySheetImportStatus.CANCELLED
        batch.save(update_fields=["status", "updated_at"])
        log_audit(request.user, batch.agency, AuditAction.IMPORT_CANCELLED, "DailySheetImportBatch", batch.id, new_values=self._metadata(batch), description="Daily sheet import cancelled.")
        return Response(self.get_serializer(batch).data)


class DailySheetViewSet(BaseSearchViewSet):
    serializer_class = DailySheetSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["agency__name", "created_by__email"]
    ordering_fields = ["transaction_date", "created_at", "status"]

    def get_queryset(self):
        queryset = DailySheet.objects.select_related(
            "agency",
            "created_by",
            "submitted_by",
            "approved_by",
            "returned_by",
            "reopened_by",
        ).prefetch_related("sheet_games", "transactions", "omitted_terminals")
        user = self.request.user
        if user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(agency__user_assignments__user=user).distinct()
        agency = self.request.query_params.get("agency")
        exact_date = self.request.query_params.get("date")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        status_value = self.request.query_params.get("status")
        created_by = self.request.query_params.get("created_by")
        if agency:
            queryset = queryset.filter(agency_id=agency)
        if exact_date:
            queryset = queryset.filter(transaction_date=exact_date)
        if date_from:
            queryset = queryset.filter(transaction_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(transaction_date__lte=date_to)
        if status_value:
            queryset = queryset.filter(status=status_value)
        if created_by:
            queryset = queryset.filter(created_by_id=created_by)
        return queryset

    def perform_create(self, serializer):
        agency = serializer.validated_data["agency"]
        require_assignment_flag(self.request.user, agency, "can_create")
        sheet = serializer.save()
        log_audit(
            self.request.user,
            sheet.agency,
            AuditAction.SHEET_CREATED,
            "DailySheet",
            sheet.id,
            new_values={"agency": sheet.agency_id, "transaction_date": sheet.transaction_date, "status": sheet.status},
            daily_sheet=sheet,
        )

    def perform_update(self, serializer):
        sheet = self.get_object()
        require_assignment_flag(self.request.user, sheet.agency, "can_edit")
        old_incoming = sheet.incoming_funds
        old_tax = sheet.tax
        updated = serializer.save()
        if old_incoming != updated.incoming_funds:
            log_audit(
                self.request.user,
                updated.agency,
                AuditAction.INCOMING_FUNDS_CHANGED,
                "DailySheet",
                updated.id,
                old_values={"incoming_funds": old_incoming},
                new_values={"incoming_funds": updated.incoming_funds},
                daily_sheet=updated,
            )
        if old_tax != updated.tax:
            log_audit(
                self.request.user,
                updated.agency,
                AuditAction.TAX_CHANGED,
                "DailySheet",
                updated.id,
                old_values={"tax": old_tax},
                new_values={"tax": updated.tax},
                daily_sheet=updated,
            )

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            return super().update(request, *args, **kwargs)

    lookup_value_regex = r"[0-9]+"

    def _destructive_reason(self, confirmation):
        if self.request.user.role != UserRole.SUPER_ADMIN:
            raise PermissionDenied("Only Super Admin may reset or delete sheets.")
        reason = self.request.data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError({"reason": "A nonblank reason is required."})
        if self.request.data.get(confirmation) is not True:
            raise ValidationError({confirmation: "Explicit confirmation is required."})
        return reason.strip()

    def _safe_sheet_metadata(self, sheet, reason):
        totals = sheet.totals()
        return {"daily_sheet_id": sheet.pk, "agency_id": sheet.agency_id,
                "agency_name": sheet.agency.name, "transaction_date": sheet.transaction_date,
                "actor": self.request.user.pk, "reason": reason,
                "previous_transaction_count": sheet.transactions.count(),
                "previous_omission_count": sheet.omitted_terminals.count(),
                "previous_net_sales": totals["gross_sales"],
                "previous_to_pay": totals["total_to_pay"], "timestamp": timezone.now()}

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def reset(self, request, pk=None):
        reason = self._destructive_reason("confirm_reset")
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            require_active_agency(sheet.agency)
            if sheet.is_archived:
                raise ValidationError({"detail": "Archived sheets cannot be reset."})
            if not sheet.can_reset:
                raise ValidationError({"detail": "Submitted sheets must first be returned; approved sheets must first be reopened."})
            metadata = self._safe_sheet_metadata(sheet, reason)
            sheet.transactions.all().delete()
            sheet.omitted_terminals.all().delete()
            sheet.incoming_funds = None
            sheet.tax = None
            sheet.reconciliation_note = ""
            sheet.save(update_fields=["incoming_funds", "tax", "reconciliation_note", "updated_at"])
            log_audit(request.user, sheet.agency, AuditAction.DAILY_SHEET_RESET,
                      "DailySheet", sheet.pk, old_values=metadata, daily_sheet=sheet)
            payload = self.get_serializer(sheet).data
        return Response(payload)

    def destroy(self, request, *args, **kwargs):
        reason = self._destructive_reason("confirm_permanent_delete")
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            require_active_agency(sheet.agency)
            if not sheet.can_delete:
                raise ValidationError({"detail": "This daily sheet cannot be deleted. Reset or archive it instead."})
            metadata = self._safe_sheet_metadata(sheet, reason)
            log_audit(request.user, sheet.agency, AuditAction.DAILY_SHEET_DELETED,
                      "DailySheet", sheet.pk, old_values=metadata)
            sheet.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        sheet = self.get_object()
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            require_active_agency(sheet.agency)
            require_assignment_flag(request.user, sheet.agency, "can_edit")
            if sheet.status not in {DailySheetStatus.DRAFT, DailySheetStatus.RETURNED, DailySheetStatus.REOPENED}:
                raise ValidationError({"status": "Only draft, returned or reopened sheets can be submitted."})
            validate_sheet_submission(sheet)
            old_status = sheet.status
            sheet.status = DailySheetStatus.SUBMITTED
            sheet.submitted_by = request.user
            sheet.submitted_at = timezone.now()
            sheet.save()
            log_audit(
                request.user,
                sheet.agency,
                AuditAction.SHEET_SUBMITTED,
                "DailySheet",
                sheet.id,
                old_values={"status": old_status},
                new_values={"status": sheet.status},
                daily_sheet=sheet,
            )
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if request.user.role != UserRole.SUPER_ADMIN:
            raise PermissionDenied("Only Super Admin may approve sheets.")
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            require_active_agency(sheet.agency)
            if sheet.status != DailySheetStatus.SUBMITTED:
                raise ValidationError({"status": "Only submitted sheets can be approved."})
            old_status = sheet.status
            sheet.status = DailySheetStatus.APPROVED
            sheet.approved_by = request.user
            sheet.approved_at = timezone.now()
            sheet.save()
            log_audit(request.user, sheet.agency, AuditAction.SHEET_APPROVED, "DailySheet", sheet.id, {"status": old_status}, {"status": sheet.status}, daily_sheet=sheet)
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_for_correction(self, request, pk=None):
        if request.user.role != UserRole.SUPER_ADMIN:
            raise PermissionDenied("Only Super Admin may return sheets.")
        comment = request.data.get("return_comment", "").strip()
        if not comment:
            raise ValidationError({"return_comment": "Return comment is required."})
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            require_active_agency(sheet.agency)
            if sheet.status != DailySheetStatus.SUBMITTED:
                raise ValidationError({"status": "Only submitted sheets can be returned."})
            old_status = sheet.status
            sheet.status = DailySheetStatus.RETURNED
            sheet.return_comment = comment
            sheet.returned_by = request.user
            sheet.returned_at = timezone.now()
            sheet.save()
            log_audit(request.user, sheet.agency, AuditAction.SHEET_RETURNED, "DailySheet", sheet.id, {"status": old_status}, {"status": sheet.status, "return_comment": comment}, comment, sheet)
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        if request.user.role != UserRole.SUPER_ADMIN:
            raise PermissionDenied("Only Super Admin may reopen sheets.")
        reason = request.data.get("reopen_reason", "").strip()
        if not reason:
            raise ValidationError({"reopen_reason": "A reopen reason is required."})
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
            require_active_agency(sheet.agency)
            if sheet.status != DailySheetStatus.APPROVED:
                raise ValidationError({"status": "Only approved sheets can be reopened."})
            old_status = sheet.status
            sheet.status = DailySheetStatus.REOPENED
            sheet.reopened_by = request.user
            sheet.reopened_at = timezone.now()
            sheet.reopen_reason = reason
            sheet.save()
            log_audit(request.user, sheet.agency, AuditAction.SHEET_REOPENED, "DailySheet", sheet.id, {"status": old_status}, {"status": sheet.status, "reopen_reason": reason}, reason, sheet)
        return Response(self.get_serializer(sheet).data)


class SheetChildWriteLockMixin:
    """Serialize child writes with reset, deletion, import and workflow actions."""
    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            sheet = DailySheet.objects.select_for_update().get(pk=serializer.validated_data["daily_sheet"].pk)
            # Revalidate after acquiring the lock: workflow or reset may have
            # changed the sheet while this request waited.
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.validated_data["daily_sheet"] = sheet
            self.perform_create(serializer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            DailySheet.objects.select_for_update().get(pk=self.get_object().daily_sheet_id)
            return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            DailySheet.objects.select_for_update().get(pk=self.get_object().daily_sheet_id)
            return super().destroy(request, *args, **kwargs)


class TPMDailyTransactionViewSet(SheetChildWriteLockMixin, BaseSearchViewSet):
    serializer_class = TPMDailyTransactionSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["tpm_code__code", "person_name_snapshot"]
    ordering_fields = ["created_at", "person_name_snapshot"]

    def get_queryset(self):
        queryset = TPMDailyTransaction.objects.select_related(
            "daily_sheet",
            "daily_sheet__agency",
            "tpm_code",
            "tpm_code__person",
            "created_by",
            "updated_by",
        ).prefetch_related("sales", "sales__daily_sheet_game")
        user = self.request.user
        if user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(daily_sheet__agency__user_assignments__user=user).distinct()
        daily_sheet = self.request.query_params.get("daily_sheet")
        if daily_sheet:
            queryset = queryset.filter(daily_sheet_id=daily_sheet)
        return queryset

    def perform_create(self, serializer):
        sheet = serializer.validated_data["daily_sheet"]
        require_assignment_flag(self.request.user, sheet.agency, "can_create")
        if self.request.user.role != UserRole.SUPER_ADMIN and not sheet.is_accountant_editable:
            raise PermissionDenied("This sheet is locked against accountant changes.")
        obj = serializer.save()
        log_audit(self.request.user, sheet.agency, AuditAction.TRANSACTION_CREATED, "TPMDailyTransaction", obj.id, new_values={"tpm_code": obj.tpm_code.code}, daily_sheet=sheet)

    def perform_update(self, serializer):
        obj = self.get_object()
        require_assignment_flag(self.request.user, obj.daily_sheet.agency, "can_edit")
        old_values = {"tpm_code": obj.tpm_code.code, "net_sales": obj.net_sales}
        updated = serializer.save()
        log_audit(self.request.user, updated.daily_sheet.agency, AuditAction.TRANSACTION_UPDATED, "TPMDailyTransaction", updated.id, old_values, {"tpm_code": updated.tpm_code.code, "net_sales": updated.net_sales}, daily_sheet=updated.daily_sheet)

    def perform_destroy(self, instance):
        require_assignment_flag(self.request.user, instance.daily_sheet.agency, "can_delete")
        if self.request.user.role != UserRole.SUPER_ADMIN and not instance.daily_sheet.is_accountant_editable:
            raise PermissionDenied("This sheet is locked against accountant deletion.")
        sheet = instance.daily_sheet
        old_values = {"tpm_code": instance.tpm_code.code, "net_sales": instance.net_sales}
        object_id = instance.id
        instance.delete()
        log_audit(self.request.user, sheet.agency, AuditAction.TRANSACTION_DELETED, "TPMDailyTransaction", object_id, old_values=old_values, daily_sheet=sheet)


class OmittedTerminalViewSet(SheetChildWriteLockMixin, BaseSearchViewSet):
    serializer_class = OmittedTerminalSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["tpm_code__code", "tpm_code__person__full_name", "reason"]
    ordering_fields = ["created_at", "tpm_code__code"]

    def get_queryset(self):
        queryset = OmittedTerminal.objects.select_related("daily_sheet", "daily_sheet__agency", "tpm_code", "tpm_code__person", "recorded_by")
        if self.request.user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(daily_sheet__agency__user_assignments__user=self.request.user).distinct()
        daily_sheet = self.request.query_params.get("daily_sheet")
        if daily_sheet:
            queryset = queryset.filter(daily_sheet_id=daily_sheet)
        return queryset

    def perform_create(self, serializer):
        sheet = serializer.validated_data["daily_sheet"]
        require_assignment_flag(self.request.user, sheet.agency, "can_edit")
        if self.request.user.role != UserRole.SUPER_ADMIN and not sheet.is_accountant_editable:
            raise PermissionDenied("This sheet is locked against accountant changes.")
        obj = serializer.save(recorded_by=self.request.user)
        log_audit(self.request.user, sheet.agency, AuditAction.OMITTED_TERMINAL_RECORDED, "OmittedTerminal", obj.id, new_values={"tpm_code": obj.tpm_code.code, "reason": obj.reason}, daily_sheet=sheet)

    def perform_destroy(self, instance):
        require_assignment_flag(self.request.user, instance.daily_sheet.agency, "can_edit")
        if self.request.user.role != UserRole.SUPER_ADMIN and not instance.daily_sheet.is_accountant_editable:
            raise PermissionDenied("This sheet is locked against accountant changes.")
        sheet = instance.daily_sheet
        old_values = {"tpm_code": instance.tpm_code.code, "reason": instance.reason}
        object_id = instance.id
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        log_audit(self.request.user, sheet.agency, AuditAction.OMITTED_TERMINAL_REMOVED, "OmittedTerminal", object_id, old_values=old_values, daily_sheet=sheet)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user", "agency", "daily_sheet")
        user = self.request.user
        if user.role != UserRole.SUPER_ADMIN:
            queryset = queryset.filter(agency__user_assignments__user=user, agency__user_assignments__can_view_history=True).exclude(model_name__in=["TerminalNumber", "TerminalImportBatch"]).distinct()
        agency = self.request.query_params.get("agency")
        daily_sheet = self.request.query_params.get("daily_sheet")
        if agency:
            queryset = queryset.filter(agency_id=agency)
        if daily_sheet:
            queryset = queryset.filter(daily_sheet_id=daily_sheet)
        return queryset
