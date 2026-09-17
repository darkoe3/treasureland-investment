"""Terminal master-data services. TPMCode remains the compatibility Sub-Agent model."""
import hashlib
from datetime import timedelta
from io import BytesIO

import openpyxl
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import filters, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .importers import normalize_identifier, safe_filename, validate_workbook_bytes
from .models import Agency, AgentType, AuditLog, Person, TPMCode, TerminalImportBatch, TerminalNumber
from .permissions import IsSuperAdmin, SuperAdminOnlyWrites
from .serializers import AuditLogSerializer


def lock_register():
    # Stable parent locks also serialize empty slots (no terminal row exists yet).
    # Five agencies today; deterministic ordering prevents cross-agency deadlocks.
    list(Agency.objects.select_for_update().order_by("pk").values_list("pk", flat=True))


def identity(terminal):
    return {"terminal_number": terminal.terminal_number, "sub_agent_number": terminal.sub_agent_number_id,
            "sub_agent_number_value": terminal.sub_agent_number.code, "person": terminal.person_id,
            "person_name": terminal.person.full_name, "agency": terminal.agency_id,
            "agency_name": terminal.agency.name, "is_active": terminal.is_active}


def audit(user, obj, action_name, old=None, reason=""):
    is_batch = isinstance(obj, TerminalImportBatch)
    # Batch events contain metadata/counts only, never workbook rows.
    new = ({"file_name": obj.original_filename, "file_hash": obj.file_hash, "status": obj.status,
            "row_count": len(obj.preview_payload.get("rows", [])), "error_count": len(obj.errors),
            "warning_count": len(obj.warnings), "result_counts": obj.result_counts,
            "mode": obj.preview_payload.get("mode", "LINK_EXISTING"),
            "creation_counts": obj.preview_payload.get("creation_counts", {}),
            "classification_counts": obj.preview_payload.get("summary", {})} if is_batch else identity(obj))
    AuditLog.objects.create(user=user, agency=obj.agency, action=action_name,
                            model_name=type(obj).__name__, object_id=str(obj.pk),
                            old_values=old or {}, new_values=new, description=reason)


def resolve_owner(data):
    for field in ("agency", "person", "sub_agent_number"):
        if isinstance(data.get(field), bool) or not str(data.get(field, "")).isdigit():
            raise ValidationError({field: "Select a valid value."})
    try:
        code = TPMCode.objects.select_for_update().select_related("person__agency").get(pk=data["sub_agent_number"])
    except TPMCode.DoesNotExist:
        raise ValidationError({"sub_agent_number": "Select an existing Sub-Agent Number."})
    if code.person_id != int(data["person"]) or code.person.agency_id != int(data["agency"]):
        raise ValidationError("Person and agency must match the selected Sub-Agent Number.")
    return code


def terminal_text(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        raise ValidationError({"terminal_number": "Enter a Terminal Number as text (1–80 characters)."})
    return value.strip()


def save_terminal(obj, user, action_name, old=None, reason=""):
    obj.updated_by = user
    obj.save()
    audit(user, obj, action_name, old, reason)
    return obj


def create_terminal(data, user):
    code = resolve_owner(data)
    active = data.get("is_active", True)
    if not isinstance(active, bool):
        raise ValidationError({"is_active": "Use true or false."})
    obj = TerminalNumber(terminal_number=terminal_text(data.get("terminal_number")),
                         sub_agent_number=code, person=code.person, agency=code.person.agency,
                         is_active=active, created_by=user, updated_by=user,
                         deactivated_at=None if active else timezone.now(), deactivated_by=None if active else user)
    return save_terminal(obj, user, "TERMINAL_CREATED")


class TerminalSerializer(serializers.ModelSerializer):
    sub_agent_number_value = serializers.CharField(source="sub_agent_number.code", read_only=True)
    person_name = serializers.CharField(source="person.full_name", read_only=True)
    agency_name = serializers.CharField(source="agency.name", read_only=True)

    class Meta:
        model = TerminalNumber
        fields = "__all__"
        read_only_fields = [f.name for f in TerminalNumber._meta.fields]


class BatchSerializer(serializers.ModelSerializer):
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = TerminalImportBatch
        fields = "__all__"
        read_only_fields = [f.name for f in TerminalImportBatch._meta.fields]

    def get_is_expired(self, obj):
        return obj.expires_at <= timezone.now()


class SafeValidationMixin:
    def handle_exception(self, exc):
        if isinstance(exc, ModelValidationError):
            exc = ValidationError(getattr(exc, "message_dict", None) or exc.messages)
        elif isinstance(exc, IntegrityError):
            exc = ValidationError("An assignment changed or this Terminal Number already exists. Refresh and try again.")
        return super().handle_exception(exc)


class TerminalNumberViewSet(SafeValidationMixin, viewsets.GenericViewSet):
    permission_classes = [SuperAdminOnlyWrites]
    serializer_class = TerminalSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["terminal_number", "sub_agent_number__code", "person__full_name", "agency__name"]

    def get_queryset(self):
        qs = TerminalNumber.objects.select_related("sub_agent_number", "person", "agency")
        if not self.request.user.is_super_admin:
            qs = qs.filter(agency__user_assignments__user=self.request.user)
        agency = self.request.query_params.get("agency")
        if agency:
            if not agency.isdigit():
                raise ValidationError({"agency": "Select a valid agency."})
            qs = qs.filter(agency_id=agency)
        active = self.request.query_params.get("active")
        if active in ("true", "false"):
            qs = qs.filter(is_active=active == "true")
        return qs

    def list(self, request):
        return Response(self.get_serializer(self.filter_queryset(self.get_queryset()), many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @transaction.atomic
    def create(self, request):
        lock_register()
        obj = create_terminal(request.data, request.user)
        return Response(self.get_serializer(obj).data, status=201)

    def locked_object(self):
        lock_register()
        return self.get_queryset().select_for_update().get(pk=self.get_object().pk)

    @transaction.atomic
    def partial_update(self, request, pk=None):
        obj = self.locked_object()
        if set(request.data) - {"terminal_number"}:
            raise ValidationError("Edit changes only the Terminal Number. Use the dedicated status or Reassign action for other changes.")
        old = identity(obj)
        obj.terminal_number = terminal_text(request.data.get("terminal_number"))
        save_terminal(obj, request.user, "TERMINAL_EDITED", old)
        return Response(self.get_serializer(obj).data)

    def change_status(self, request, active):
        obj = self.locked_object()
        if obj.is_active != active:
            old = identity(obj)
            obj.is_active = active
            obj.deactivated_at = None if active else timezone.now()
            obj.deactivated_by = None if active else request.user
            save_terminal(obj, request.user, "TERMINAL_REACTIVATED" if active else "TERMINAL_DEACTIVATED", old)
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def deactivate(self, request, pk=None):
        return self.change_status(request, False)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reactivate(self, request, pk=None):
        return self.change_status(request, True)

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    @transaction.atomic
    def reassign(self, request, pk=None):
        obj = self.locked_object()
        reason = request.data.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValidationError({"reason": "Enter a reason (1–2000 characters)."})
        if request.data.get("confirmed") is not True:
            raise ValidationError({"confirmed": "Explicit confirmation is required."})
        code = resolve_owner(request.data)
        if code.pk == obj.sub_agent_number_id:
            raise ValidationError("Choose a different Sub-Agent Number.")
        # An occupied target is never silently replaced: deactivate its terminal first.
        if TerminalNumber.objects.filter(sub_agent_number=code, is_active=True).exclude(pk=obj.pk).exists():
            raise ValidationError("Target already has an active terminal. Explicitly deactivate it before reassignment.")
        old = identity(obj)
        obj.sub_agent_number, obj.person, obj.agency = code, code.person, code.person.agency
        save_terminal(obj, request.user, "TERMINAL_REASSIGNED", old, reason.strip())
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["get"], permission_classes=[IsSuperAdmin])
    def history(self, request, pk=None):
        obj = self.get_object()
        logs = AuditLog.objects.filter(model_name="TerminalNumber", object_id=str(obj.pk))
        return Response(AuditLogSerializer(logs, many=True).data)


def normalize_name(value):
    return " ".join(str(value or "").split()).casefold()


def classify(code, number):
    existing = TerminalNumber.objects.filter(terminal_number__iexact=number).first()
    occupied = TerminalNumber.objects.filter(sub_agent_number=code, is_active=True).first()
    if existing and existing.sub_agent_number_id != code.id:
        return "Reassignment required", "Use Reassign with a reason and confirmation, then upload a fresh preview."
    if occupied and (not existing or occupied.pk != existing.pk):
        return "Conflict", "Sub-Agent Number already has an active terminal. Explicitly deactivate it before replacement."
    if existing:
        if not existing.is_active:
            return "Update required", "Reactivate the existing terminal explicitly, then upload a fresh preview."
        return "Unchanged", ""
    return "New", ""


CATEGORIES = ("CREATE_PERSON_SUBAGENT_TERMINAL", "ADD_SUBAGENT_TO_EXISTING_PERSON",
              "ADD_TERMINAL_TO_EXISTING_SUBAGENT", "UNCHANGED", "REASSIGNMENT_REQUIRED",
              "NAME_CONFLICT", "AGENCY_CONFLICT", "DUPLICATE", "INVALID")
NEW_CATEGORIES = CATEGORIES[:3]


def resolve_import_row(sub, number, name, agency, mode):
    code = TPMCode.objects.select_related("person__agency").filter(code__iexact=sub).first()
    person = code.person if code else None
    category, message = "INVALID", ""
    terminal = TerminalNumber.objects.filter(terminal_number__iexact=number).first()
    if (code and code.person.agency_id != agency.pk) or (terminal and terminal.agency_id != agency.pk):
        category, message = "AGENCY_CONFLICT", "Identifier belongs to another agency. Resolve manually."
    elif code and normalize_name(name) != normalize_name(person.full_name):
        category, message = "NAME_CONFLICT", "NAME does not match the database person."
    elif code and (not code.is_active or not person.is_active):
        message = "Sub-Agent Number and person must be active."
    elif terminal and (not code or terminal.sub_agent_number_id != code.pk):
        category, message = "REASSIGNMENT_REQUIRED", "Use the dedicated Reassign workflow."
    elif code:
        state, message = classify(code, number)
        category = {"New": "ADD_TERMINAL_TO_EXISTING_SUBAGENT", "Unchanged": "UNCHANGED",
                    "Conflict": "REASSIGNMENT_REQUIRED", "Reassignment required": "REASSIGNMENT_REQUIRED",
                    "Update required": "REASSIGNMENT_REQUIRED"}[state]
    elif mode == "LINK_EXISTING":
        message = "Sub-Agent Number does not exist in the selected agency."
    else:
        matches = [p for p in Person.objects.filter(agency=agency) if normalize_name(p.full_name) == normalize_name(name)]
        if len(matches) > 1:
            category, message = "NAME_CONFLICT", "Multiple people have this normalized NAME. Manual resolution required."
        elif matches:
            person = matches[0]
            if not person.is_active:
                message = "Matching person is inactive. Resolve manually."
            else:
                category = "ADD_SUBAGENT_TO_EXISTING_PERSON"
        else:
            category = "CREATE_PERSON_SUBAGENT_TERMINAL"
    return category, message, code.pk if code else None, person.pk if person else None


def creation_counts(rows):
    return {"people": len({normalize_name(r["name"]) for r in rows if r["classification"] == NEW_CATEGORIES[0]}),
            "sub_agent_numbers": sum(r["classification"] in NEW_CATEGORIES[:2] for r in rows),
            "terminals": sum(r["classification"] in NEW_CATEGORIES for r in rows)}


def parse_terminal_workbook(upload, agency, mode="LINK_EXISTING"):
    data = validate_workbook_bytes(upload)
    errors, warnings, rows = [], [], []
    try:
        workbook = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise ValidationError("Workbook is corrupt or unsupported.") from exc
    try:
        if len(workbook.sheetnames) > 10:
            raise ValidationError("Workbook has too many worksheets.")
        sheet = workbook.worksheets[0]
        if sheet.max_row > 5001 or sheet.max_column > 20:
            raise ValidationError("Workbook exceeds the 5,000-row or 20-column limit.")
        if [str(sheet.cell(1, col).value or "").strip().upper() for col in range(1, 5)] != ["S/NOS", "SUB AGT NOS", "TERMINAL NOS", "NAME"]:
            raise ValidationError("Row 1 must contain S/NOS, SUB AGT NOS, TERMINAL NOS, NAME in columns A–D.")
        seen_sub, seen_terminal = set(), set()
        for n, cells in enumerate(sheet.iter_rows(min_row=2, min_col=2, max_col=4), 2):
            if all(cell.value is None or str(cell.value).strip() == "" for cell in cells):
                continue
            row_errors, row_warnings = [], []
            if any(cell.data_type == "f" for cell in cells):
                row_errors.append("Formula cells are not allowed in columns B–D.")
                values = ["" if c.data_type == "f" else c.value for c in cells]
            else:
                values = [c.value for c in cells]
            if any(isinstance(value, bool) for value in values):
                row_errors.append("Boolean cells are not valid identifiers or names.")
            sub = normalize_identifier(values[0], f"B{n}", row_warnings)
            number = normalize_identifier(values[1], f"C{n}", row_warnings)
            name = str(values[2] or "").strip()
            if not sub or not number or not name:
                row_errors.append("SUB AGT NOS, TERMINAL NOS and NAME are required.")
            if len(sub) > 80 or len(number) > 80 or len(name) > 255:
                row_errors.append("Identifier or name exceeds the allowed length.")
            for value, seen, label in ((sub, seen_sub, "Sub-Agent Number"), (number, seen_terminal, "Terminal Number")):
                if value.casefold() in seen:
                    row_errors.append(f"Duplicate {label} in workbook.")
                if value:
                    seen.add(value.casefold())
            classification, code_id, person_id = "INVALID", None, None
            if not row_errors:
                classification, message, code_id, person_id = resolve_import_row(sub, number, name, agency, mode)
                if message:
                    row_errors.append(message)
            elif any(message.startswith("Duplicate") for message in row_errors):
                classification = "DUPLICATE"
            rows.append({"row": n, "sub_agent_number": code_id, "sub_agent_number_value": sub[:80],
                         "terminal_number": number[:80], "person": person_id,
                         "name": name[:255], "classification": classification})
            errors.extend({"row": n, "category": classification, "detail": message,
                           "message": f"Row {n}: {message}"} for message in row_errors)
            for warning in row_warnings:
                field = "SUB AGT NOS" if warning["cell"].startswith("B") else "TERMINAL NOS"
                warnings.append({"row": n, "field": field,
                                 "message": f"Row {n} — {field} is numeric and may have lost leading zeroes."})
        if not rows:
            errors.append({"row": 2, "message": "Row 2: Workbook contains no completed rows."})
    finally:
        workbook.close()
    return data, {"mode": mode, "rows": rows, "creation_counts": creation_counts(rows),
                  "summary": {category: sum(r["classification"] == category for r in rows) for category in CATEGORIES}}, warnings, errors


class TerminalImportViewSet(SafeValidationMixin, viewsets.GenericViewSet):
    permission_classes = [IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = BatchSerializer

    def get_queryset(self):
        # Even Super Admins can only confirm/cancel their own previews.
        return TerminalImportBatch.objects.filter(uploader=self.request.user)

    def agency(self, data):
        if not str(data.get("agency", "")).isdigit():
            raise ValidationError({"agency": "Select an agency."})
        try:
            return Agency.objects.get(pk=data["agency"], is_active=True)
        except Agency.DoesNotExist:
            raise ValidationError({"agency": "Select an active agency."})

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=False, methods=["get"])
    def template(self, request):
        self.agency(request.query_params)
        wb = openpyxl.Workbook()
        sheet = wb.active
        sheet.title = "Terminal Register"
        sheet.append(["S/NOS", "SUB AGT NOS", "TERMINAL NOS", "NAME"])
        for col in ("B", "C"):
            sheet.column_dimensions[col].number_format = "@"
        for n in range(2, 5002):
            for col in (2, 3):
                cell = sheet.cell(n, col, "")
                cell.data_type, cell.number_format = "s", "@"
        for col, width in (("A", 10), ("B", 25), ("C", 25), ("D", 35)):
            sheet.column_dimensions[col].width = width
        sheet.freeze_panes = "A2"
        instructions = wb.create_sheet("Instructions")
        for text in ("Choose the same agency when uploading. Data starts on row 2 of Terminal Register.",
                     "S/NOS is ignored. LINK_EXISTING requires existing people and Sub-Agent Numbers.",
                     "Keep identifiers as Text to preserve leading zeroes. Do not paste numeric cells.",
                     "ONBOARD_MISSING can create missing people and Sub-Agent Numbers after explicit confirmation. Existing names must match.",
                     "All three fields B–D are required. No formulas, macros or external links.",
                     "Preview first. Resolve conflicts using Edit, Deactivate, Reactivate or Reassign, then upload again."):
            instructions.append([text])
        instructions.column_dimensions["A"].width = 110
        buffer = BytesIO()
        wb.save(buffer)
        response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="terminal-register.xlsx"'
        return response

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def preview(self, request):
        agency = self.agency(request.data)
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Upload an .xlsx workbook."})
        mode = request.data.get("mode", "LINK_EXISTING")
        if mode not in ("LINK_EXISTING", "ONBOARD_MISSING"):
            raise ValidationError({"mode": "Select a valid import mode."})
        data, payload, warnings, errors = parse_terminal_workbook(upload, agency, mode)
        batch = TerminalImportBatch.objects.create(uploader=request.user, agency=agency,
            original_filename=safe_filename(upload.name.replace("\\", "/")), file_hash=hashlib.sha256(data).hexdigest(),
            preview_payload=payload, warnings=warnings, errors=errors, expires_at=timezone.now() + timedelta(hours=1))
        audit(request.user, batch, "TERMINAL_IMPORT_PREVIEWED")
        return Response(self.get_serializer(batch).data, status=201)

    def locked_batch(self):
        batch = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
        if batch.status != "PREVIEWED":
            raise ValidationError("Only a previewed batch may be confirmed or cancelled.")
        if batch.expires_at <= timezone.now():
            raise ValidationError("This preview expired. Upload a fresh workbook.")
        return batch

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def confirm(self, request, pk=None):
        lock_register()
        batch = self.locked_batch()
        if request.data.get("confirmed") is not True:
            raise ValidationError("Explicit confirmation is required.")
        if batch.errors:
            raise ValidationError("Resolve all blocking errors and create a fresh preview.")
        if not batch.agency.is_active:
            raise ValidationError("Agency is inactive.")
        mode = batch.preview_payload.get("mode", "LINK_EXISTING")
        reason = request.data.get("reason", "")
        if batch.warnings and request.data.get("warnings_acknowledged") is not True:
            raise ValidationError("Verify numeric identifiers against the original source and acknowledge warnings.")
        if mode == "ONBOARD_MISSING":
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
                raise ValidationError("Enter an onboarding reason (1–2000 characters).")
            if request.data.get("acknowledged_counts") != batch.preview_payload["creation_counts"]:
                raise ValidationError("Explicitly acknowledge the displayed creation counts.")
        # Lock existing owners as well as parent agencies; validate the complete plan before writes.
        list(Person.objects.select_for_update().filter(agency=batch.agency).order_by("pk"))
        list(TPMCode.objects.select_for_update().order_by("pk"))
        list(TerminalNumber.objects.select_for_update().order_by("pk"))
        for row in batch.preview_payload["rows"]:
            category, message, code_id, person_id = resolve_import_row(
                row["sub_agent_number_value"], row["terminal_number"], row["name"], batch.agency, mode)
            if message or (category, code_id, person_id) != (row["classification"], row["sub_agent_number"], row["person"]):
                raise ValidationError(f"Row {row['row']}: Identity or assignment changed after preview. Upload again.")
        counts = {"created": 0, "unchanged": 0}
        new_people = {}
        for row in batch.preview_payload["rows"]:
            if row["classification"] == "UNCHANGED":
                counts["unchanged"] += 1
                continue
            person_id, code_id = row["person"], row["sub_agent_number"]
            if not person_id:
                key = normalize_name(row["name"])
                if key not in new_people:
                    new_people[key] = Person.objects.create(agency=batch.agency,
                        full_name=" ".join(row["name"].split()), agent_type=AgentType.SUBAGENT).pk
                person_id = new_people[key]
            if not code_id:
                code_id = TPMCode.objects.create(person_id=person_id, code=row["sub_agent_number_value"]).pk
            create_terminal({**row, "person": person_id, "sub_agent_number": code_id, "agency": batch.agency_id}, request.user)
            counts["created"] += 1
        if mode == "ONBOARD_MISSING":
            counts.update(batch.preview_payload["creation_counts"])
        batch.status, batch.confirmed_at, batch.result_counts = "CONFIRMED", timezone.now(), counts
        batch.save()
        audit(request.user, batch, "TERMINAL_IMPORT_CONFIRMED", reason=reason.strip() if mode == "ONBOARD_MISSING" else "")
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, pk=None):
        batch = self.locked_batch()
        batch.status = "CANCELLED"
        batch.save()
        audit(request.user, batch, "TERMINAL_IMPORT_CANCELLED")
        return Response(self.get_serializer(batch).data)
