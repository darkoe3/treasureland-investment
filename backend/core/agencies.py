"""Agency lifecycle helpers; all writers lock agency parents before child rows."""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import Agency, AuditLog, DailySheetStatus, TPMCode


def require_active_agency(agency):
    if not Agency.objects.filter(pk=agency.pk, is_active=True).exists():
        raise ValidationError({"agency": "This agency is inactive. Reactivate it before making changes."})


class AgencyWriteLockMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            with transaction.atomic():
                list(Agency.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
                return super().dispatch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)


def agency_counts(agency):
    codes = TPMCode.objects.filter(person__agency=agency)
    return {
        "assigned_accountants": agency.user_assignments.count(),
        "people": agency.people.count(), "sub_agent_numbers": codes.count(),
        "terminal_numbers": agency.terminal_numbers.count(),
        "daily_sheets": agency.daily_sheets.count(),
        "active_people": agency.people.filter(is_active=True).count(),
        "active_sub_agent_numbers": codes.filter(is_active=True).count(),
        "active_terminal_numbers": agency.terminal_numbers.filter(is_active=True).count(),
        "editable_daily_sheets": agency.daily_sheets.filter(is_archived=False, status__in=[
            DailySheetStatus.DRAFT, DailySheetStatus.RETURNED, DailySheetStatus.REOPENED]).count(),
    }


def agency_identity(agency):
    return {"agency_id": agency.pk, "name": agency.name, "code": agency.code, "is_active": agency.is_active}


def agency_audit(user, agency, action, previous=None, reason="", impact=None):
    AuditLog.objects.create(user=user, agency=agency, action=action, model_name="Agency",
        object_id=str(agency.pk), old_values=previous or {},
        new_values={**agency_identity(agency), "actor_id": user.pk, "reason": reason,
                    **({"impact": impact} if impact is not None else {})})
