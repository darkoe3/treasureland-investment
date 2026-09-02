from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    Agency,
    AuditLog,
    DailySheet,
    DailySheetImportBatch,
    DailySheetGame,
    Game,
    OmittedTerminal,
    Person,
    TPMCode,
    TPMDailyTransaction,
    TransactionGameSale,
    User,
    UserAgencyAssignment,
    WeeklyGameSchedule,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("email", "full_name", "role", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_staff", "created_at")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "password1", "password2", "is_active", "is_staff"),
        }),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "code")
    ordering = ("name",)


@admin.register(UserAgencyAssignment)
class UserAgencyAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "agency", "can_create", "can_edit", "can_delete", "can_export", "can_view_history")
    list_filter = ("agency", "can_create", "can_edit", "can_delete", "can_export", "can_view_history")
    search_fields = ("user__email", "user__full_name", "agency__name", "agency__code")
    ordering = ("agency__name", "user__email")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("full_name", "agency", "agent_type", "is_active", "created_at")
    list_filter = ("agency", "agent_type", "is_active", "created_at")
    search_fields = ("full_name", "agency__name", "tpm_codes__code")
    ordering = ("full_name",)


@admin.register(TPMCode)
class TPMCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "person", "get_agency", "is_active", "created_at")
    list_filter = ("is_active", "person__agency", "created_at")
    search_fields = ("code", "person__full_name", "person__agency__name")
    ordering = ("code",)

    @admin.display(ordering="person__agency__name", description="Agency")
    def get_agency(self, obj):
        return obj.person.agency


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(WeeklyGameSchedule)
class WeeklyGameScheduleAdmin(admin.ModelAdmin):
    list_display = ("game", "weekday", "is_whole_day", "closing_time", "draw_time", "display_order", "is_active")
    list_filter = ("weekday", "is_whole_day", "is_active", "game")
    search_fields = ("game__name",)
    ordering = ("weekday", "display_order", "id")


class DailySheetGameInline(admin.TabularInline):
    model = DailySheetGame
    extra = 0
    readonly_fields = ("game_name_snapshot", "is_whole_day_snapshot", "closing_time_snapshot", "draw_time_snapshot", "display_order", "created_at")


@admin.register(DailySheet)
class DailySheetAdmin(admin.ModelAdmin):
    list_display = ("agency", "transaction_date", "status", "incoming_funds", "tax", "gross_sales", "total_to_pay", "created_by")
    list_filter = ("status", "agency", "transaction_date", "created_at")
    search_fields = ("agency__name", "created_by__email", "reconciliation_note", "return_comment", "reopen_reason")
    date_hierarchy = "transaction_date"
    readonly_fields = ("created_at", "updated_at", "gross_sales", "total_to_pay", "commission", "variance", "variance_status")
    inlines = [DailySheetGameInline]

    @admin.display(description="Gross Sales")
    def gross_sales(self, obj):
        return obj.totals()["gross_sales"]

    @admin.display(description="Total To Pay")
    def total_to_pay(self, obj):
        return obj.totals()["total_to_pay"]

    @admin.display(description="Commission")
    def commission(self, obj):
        return obj.totals()["commission"]

    @admin.display(description="Variance")
    def variance(self, obj):
        return obj.totals()["variance"]

    @admin.display(description="Variance Status")
    def variance_status(self, obj):
        return obj.totals()["variance_status"]


@admin.register(DailySheetGame)
class DailySheetGameAdmin(admin.ModelAdmin):
    list_display = ("daily_sheet", "game_name_snapshot", "is_whole_day_snapshot", "closing_time_snapshot", "draw_time_snapshot", "display_order", "created_at")
    list_filter = ("daily_sheet__agency", "game")
    search_fields = ("game_name_snapshot", "daily_sheet__agency__name")
    date_hierarchy = "created_at"


@admin.register(DailySheetImportBatch)
class DailySheetImportBatchAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "agency", "transaction_date", "status", "uploader", "created_at", "confirmed_at")
    list_filter = ("status", "agency", "transaction_date", "created_at")
    search_fields = ("original_filename", "file_hash", "uploader__email", "agency__name")
    readonly_fields = ("uploader", "agency", "transaction_date", "original_filename", "file_hash", "status", "preview_payload", "warnings", "errors", "existing_sheet", "existing_transaction_count", "confirmed_sheet", "confirmed_at", "expires_at", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False


class TransactionGameSaleInline(admin.TabularInline):
    model = TransactionGameSale
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(TPMDailyTransaction)
class TPMDailyTransactionAdmin(admin.ModelAdmin):
    list_display = ("daily_sheet", "tpm_code", "person_name_snapshot", "agent_type_snapshot", "net_sales", "commission", "to_pay", "created_by")
    list_filter = ("daily_sheet__agency", "agent_type_snapshot", "created_at")
    search_fields = ("tpm_code__code", "person_name_snapshot", "daily_sheet__agency__name")
    date_hierarchy = "created_at"
    readonly_fields = ("person_name_snapshot", "agent_type_snapshot", "net_sales", "commission", "to_pay", "created_at", "updated_at")
    inlines = [TransactionGameSaleInline]


@admin.register(TransactionGameSale)
class TransactionGameSaleAdmin(admin.ModelAdmin):
    list_display = ("transaction", "daily_sheet_game", "amount", "created_at")
    list_filter = ("daily_sheet_game__daily_sheet__agency", "daily_sheet_game__game")
    search_fields = ("transaction__tpm_code__code", "daily_sheet_game__game_name_snapshot")
    date_hierarchy = "created_at"


@admin.register(OmittedTerminal)
class OmittedTerminalAdmin(admin.ModelAdmin):
    list_display = ("daily_sheet", "tpm_code", "recorded_by", "created_at")
    list_filter = ("daily_sheet__agency", "created_at")
    search_fields = ("tpm_code__code", "tpm_code__person__full_name", "reason")
    date_hierarchy = "created_at"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "agency", "daily_sheet", "user", "model_name", "object_id")
    list_filter = ("action", "agency", "created_at")
    search_fields = ("user__email", "agency__name", "model_name", "object_id", "description")
    date_hierarchy = "created_at"
    readonly_fields = ("user", "agency", "daily_sheet", "action", "model_name", "object_id", "old_values", "new_values", "description", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
