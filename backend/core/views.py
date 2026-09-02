from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

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
from .importers import parse_daily_sheet_workbook
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
    PersonSerializer,
    TPMCodeSerializer,
    TPMDailyTransactionSerializer,
    UserAgencyAssignmentSerializer,
    WeeklyGameScheduleSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    pass


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


class BaseSearchViewSet(viewsets.ModelViewSet):
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]


def assignment_for(user, agency):
    if user.role == UserRole.SUPER_ADMIN:
        return None
    return UserAgencyAssignment.objects.filter(user=user, agency=agency).first()


def require_assignment_flag(user, agency, flag):
    if user.role == UserRole.SUPER_ADMIN:
        return
    assignment = assignment_for(user, agency)
    if not assignment or not getattr(assignment, flag):
        raise PermissionDenied(f"You do not have {flag} permission for this agency.")


def accessible_agency_ids(user, flag=None):
    if user.role == UserRole.SUPER_ADMIN:
        return None
    queryset = UserAgencyAssignment.objects.filter(user=user, agency__is_active=True)
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
        raise ValidationError({"omitted_terminals": "Every active TPM code must be entered or omitted with an explanation."})
    if entered_ids & omitted_ids:
        raise ValidationError({"tpm_code": "A TPM code cannot be both entered and omitted."})
    game_count = sheet.sheet_games.count()
    for tpm_transaction in sheet.transactions.all():
        if tpm_transaction.sales.count() != game_count:
            raise ValidationError({"sales": "Every transaction must have one sale entry for every game on the sheet."})
    if sheet.transactions.values("tpm_code").distinct().count() != sheet.transactions.count():
        raise ValidationError({"tpm_code": "Duplicate TPM codes are not allowed."})
    if sheet.totals()["variance"] != 0 and not sheet.reconciliation_note.strip():
        raise ValidationError({"reconciliation_note": "A reconciliation note is required when variance is not zero."})


class AgencyViewSet(BaseSearchViewSet):
    serializer_class = AgencySerializer
    permission_classes = [SuperAdminOrReadOnlyAccountant]
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]

    def get_queryset(self):
        queryset = Agency.objects.all()
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(user_assignments__user=self.request.user).distinct()


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

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        accountant = self.get_object()
        serializer = AccountantPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        accountant.set_password(serializer.validated_data["password"])
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

    def perform_create(self, serializer):
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

    def perform_update(self, serializer):
        person = self.get_object()
        require_assignment_flag(self.request.user, person.agency, "can_edit")
        new_agency = serializer.validated_data.get("agency", person.agency)
        require_assignment_flag(self.request.user, new_agency, "can_edit")
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

    def perform_create(self, serializer):
        person = serializer.validated_data["person"]
        require_assignment_flag(self.request.user, person.agency, "can_create")
        code = serializer.save()
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
        old_values = {"person": code.person_id, "code": code.code, "is_active": code.is_active}
        updated = serializer.save()
        log_audit(
            self.request.user,
            updated.person.agency,
            "TPM_CODE_UPDATED",
            "TPMCode",
            updated.id,
            old_values=old_values,
            new_values={"person": updated.person_id, "code": updated.code, "is_active": updated.is_active},
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
            description=f"TPM code deactivated: {instance.code}",
        )


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


class DailySheetImportBatchViewSet(viewsets.GenericViewSet):
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
        agency_id = request.data.get("agency")
        if not str(agency_id or "").isdigit():
            raise ValidationError({"agency": "Select a valid agency."})
        try:
            agency = Agency.objects.get(pk=int(agency_id), is_active=True)
        except Agency.DoesNotExist as exc:
            raise ValidationError({"agency": "Select an active agency."}) from exc
        require_assignment_flag(request.user, agency, "can_create")
        return agency

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
        batch = self.get_object()
        require_assignment_flag(request.user, batch.agency, "can_create")
        replace_existing = request.data.get("replace_existing") is True
        acknowledge_date_mismatch = request.data.get("acknowledge_date_mismatch") is True

        with transaction.atomic():
            batch = self.get_queryset().select_for_update().get(pk=batch.pk)
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
                    tpm_code = TPMCode.objects.select_related("person").get(
                        pk=row["tpm_code_id"],
                        person__agency=batch.agency,
                        person__is_active=True,
                        is_active=True,
                    )
                except TPMCode.DoesNotExist as exc:
                    raise ValidationError({"tpm_code": "A TPM Code changed after preview. Create a fresh preview."}) from exc
                txn = TPMDailyTransaction.objects.create(
                    daily_sheet=sheet,
                    tpm_code=tpm_code,
                    created_by=request.user,
                    updated_by=request.user,
                )
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

    def perform_destroy(self, instance):
        require_assignment_flag(self.request.user, instance.agency, "can_delete")
        if self.request.user.role != UserRole.SUPER_ADMIN and not instance.is_accountant_editable:
            raise PermissionDenied("This sheet is locked against accountant deletion.")
        instance.delete()

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        sheet = self.get_object()
        return Response(self.get_serializer(sheet).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        with transaction.atomic():
            sheet = DailySheet.objects.select_for_update().get(pk=self.get_object().pk)
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


class TPMDailyTransactionViewSet(BaseSearchViewSet):
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


class OmittedTerminalViewSet(BaseSearchViewSet):
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
            queryset = queryset.filter(agency__user_assignments__user=user, agency__user_assignments__can_view_history=True).distinct()
        agency = self.request.query_params.get("agency")
        daily_sheet = self.request.query_params.get("daily_sheet")
        if agency:
            queryset = queryset.filter(agency_id=agency)
        if daily_sheet:
            queryset = queryset.filter(daily_sheet_id=daily_sheet)
        return queryset
