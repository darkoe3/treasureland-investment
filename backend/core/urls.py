from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AgencyViewSet,
    AccountantViewSet,
    AuditLogViewSet,
    DailySheetViewSet,
    DailySheetImportBatchViewSet,
    GameViewSet,
    LoginView,
    OmittedTerminalViewSet,
    PaymentAnalyticsView,
    PaymentObligationViewSet,
    PaymentPayerViewSet,
    PayerPaymentViewSet,
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

from .terminal_register import TerminalNumberViewSet, TerminalImportViewSet

router = DefaultRouter()
router.register("terminal-numbers", TerminalNumberViewSet, basename="terminal-number")
router.register("terminal-number-imports", TerminalImportViewSet, basename="terminal-number-import")
router.register("agencies", AgencyViewSet, basename="agency")
router.register("accountants", AccountantViewSet, basename="accountant")
router.register("agency-assignments", UserAgencyAssignmentViewSet, basename="agency-assignment")
router.register("people", PersonViewSet, basename="person")
router.register("tpm-codes", TPMCodeViewSet, basename="tpm-code")
router.register("games", GameViewSet, basename="game")
router.register("weekly-game-schedules", WeeklyGameScheduleViewSet, basename="weekly-game-schedule")
router.register("daily-sheets", DailySheetViewSet, basename="daily-sheet")
router.register("daily-sheet-imports", DailySheetImportBatchViewSet, basename="daily-sheet-import")
router.register("tpm-daily-transactions", TPMDailyTransactionViewSet, basename="tpm-daily-transaction")
router.register("omitted-terminals", OmittedTerminalViewSet, basename="omitted-terminal")
router.register("audit-logs", AuditLogViewSet, basename="audit-log")
router.register("payment-payers", PaymentPayerViewSet, basename="payment-payer")
router.register("payment-obligations", PaymentObligationViewSet, basename="payment-obligation")
router.register("payer-payments", PayerPaymentViewSet, basename="payer-payment")

urlpatterns = [
    path("health/", health_view, name="health"),
    path("auth/login/", LoginView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", RefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", logout_view, name="token_blacklist"),
    path("auth/me/", current_user_view, name="current_user"),
    path("reports/agency-summary/", agency_summary_report_view, name="agency_summary_report"),
    path("reports/agency-summary/export/", agency_summary_report_export_view, name="agency_summary_report_export"),
    path("payments/analytics/", PaymentAnalyticsView.as_view(), name="payments-analytics"),
    path("", include(router.urls)),
]
