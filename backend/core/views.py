from django.db import transaction
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import (
    Agency,
    AuditAction,
    AuditLog,
    DailySheet,
    DailySheetStatus,
    Game,
    OmittedTerminal,
    Person,
    TPMCode,
    TPMDailyTransaction,
    TransactionGameSale,
    UserAgencyAssignment,
    UserRole,
    WeeklyGameSchedule,
    json_safe_value,
)
from .permissions import IsSuperAdmin, SuperAdminOnlyWrites, SuperAdminOrReadOnlyAccountant
from .serializers import (
    AgencySerializer,
    AuditLogSerializer,
    DailySheetGameSerializer,
    DailySheetSerializer,
    EmailTokenObtainPairSerializer,
    GameSerializer,
    OmittedTerminalSerializer,
    PersonSerializer,
    TPMCodeSerializer,
    TPMDailyTransactionSerializer,
    UserAgencyAssignmentSerializer,
    UserProfileSerializer,
    WeeklyGameScheduleSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    pass


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
    return Response(UserProfileSerializer(request.user).data)


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
    omitted_ids = set(sheet.omitted_terminals.values_list("tpm_code_id", flat=True))
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


class PersonViewSet(BaseSearchViewSet):
    serializer_class = PersonSerializer
    permission_classes = [SuperAdminOnlyWrites]
    search_fields = ["full_name", "agency__name", "tpm_codes__code"]
    ordering_fields = ["full_name", "created_at"]

    def get_queryset(self):
        queryset = Person.objects.select_related("agency").prefetch_related("tpm_codes")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(agency__user_assignments__user=self.request.user).distinct()


class TPMCodeViewSet(BaseSearchViewSet):
    serializer_class = TPMCodeSerializer
    permission_classes = [SuperAdminOnlyWrites]
    search_fields = ["code", "person__full_name", "person__agency__name"]
    ordering_fields = ["code", "created_at"]

    def get_queryset(self):
        queryset = TPMCode.objects.select_related("person", "person__agency")
        if self.request.user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(person__agency__user_assignments__user=self.request.user).distinct()


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
        ).order_by("display_order", "closing_time", "id")
        return Response(WeeklyGameScheduleSerializer(schedules, many=True).data)


class WeeklyGameScheduleViewSet(BaseSearchViewSet):
    serializer_class = WeeklyGameScheduleSerializer
    permission_classes = [SuperAdminOnlyWrites]
    queryset = WeeklyGameSchedule.objects.select_related("game")
    search_fields = ["game__name"]
    ordering_fields = ["weekday", "display_order", "closing_time"]


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
        instance.delete()
        log_audit(self.request.user, sheet.agency, AuditAction.OMITTED_TERMINAL_REMOVED, "OmittedTerminal", object_id, old_values=old_values, daily_sheet=sheet)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user", "agency", "daily_sheet")
        user = self.request.user
        if user.role == UserRole.SUPER_ADMIN:
            return queryset
        return queryset.filter(agency__user_assignments__user=user, agency__user_assignments__can_view_history=True).distinct()
