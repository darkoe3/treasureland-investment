from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Agency, Game, Person, TPMCode, User, UserAgencyAssignment, WeeklyGameSchedule


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
    list_display = ("game", "weekday", "closing_time", "draw_time", "display_order", "is_active")
    list_filter = ("weekday", "is_active", "game")
    search_fields = ("game__name",)
    ordering = ("weekday", "display_order", "closing_time")
