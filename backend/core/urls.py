from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AgencyViewSet,
    AccountantViewSet,
    AuditLogViewSet,
    DailySheetViewSet,
    GameViewSet,
    LoginView,
    OmittedTerminalViewSet,
    PersonViewSet,
    RefreshView,
    TPMCodeViewSet,
    TPMDailyTransactionViewSet,
    UserAgencyAssignmentViewSet,
    WeeklyGameScheduleViewSet,
    agency_summary_report_export_view,
    agency_summary_report_view,
    current_user_view,
    health_view,
    logout_view,
)

router = DefaultRouter()
router.register("agencies", AgencyViewSet, basename="agency")
router.register("accountants", AccountantViewSet, basename="accountant")
router.register("agency-assignments", UserAgencyAssignmentViewSet, basename="agency-assignment")
router.register("people", PersonViewSet, basename="person")
router.register("tpm-codes", TPMCodeViewSet, basename="tpm-code")
router.register("games", GameViewSet, basename="game")
router.register("weekly-game-schedules", WeeklyGameScheduleViewSet, basename="weekly-game-schedule")
router.register("daily-sheets", DailySheetViewSet, basename="daily-sheet")
router.register("tpm-daily-transactions", TPMDailyTransactionViewSet, basename="tpm-daily-transaction")
router.register("omitted-terminals", OmittedTerminalViewSet, basename="omitted-terminal")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")

urlpatterns = [
    path("health/", health_view, name="health"),
    path("auth/login/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", RefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", logout_view, name="token_blacklist"),
    path("auth/me/", current_user_view, name="current_user"),
    path("reports/agency-summary/", agency_summary_report_view, name="agency_summary_report"),
    path("reports/agency-summary/export/", agency_summary_report_export_view, name="agency_summary_report_export"),
    path("", include(router.urls)),
]
