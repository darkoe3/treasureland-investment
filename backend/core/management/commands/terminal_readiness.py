"""Read-only checks. Never infer or create terminal assignments."""
import json

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q
from django.db.models.functions import Lower

from core.models import TPMCode, TPMDailyTransaction, TerminalNumber


class Command(BaseCommand):
    help = "Read-only terminal register readiness report; does not modify data."

    def handle(self, *args, **options):
        active_ids = TerminalNumber.objects.filter(is_active=True).values("sub_agent_number_id")
        payload = {
            "active_sub_agents_without_terminals": list(TPMCode.objects.filter(is_active=True).exclude(pk__in=active_ids).values("id", "code", "person_id")),
            "inactive_sub_agents": list(TPMCode.objects.filter(is_active=False).values("id", "code", "person_id")),
            "duplicate_terminal_numbers": list(TerminalNumber.objects.annotate(normalized=Lower("terminal_number")).values("normalized").annotate(count=Count("id")).filter(count__gt=1)),
            "duplicate_active_assignments": list(TerminalNumber.objects.filter(is_active=True).values("sub_agent_number_id").annotate(count=Count("id")).filter(count__gt=1)),
            "conflicting_relationships": list(TerminalNumber.objects.filter(~Q(person_id=F("sub_agent_number__person_id")) | ~Q(agency_id=F("sub_agent_number__person__agency_id"))).values("id", "terminal_number", "sub_agent_number_id", "person_id", "agency_id")),
            "historical_transactions_without_terminal_snapshot": TPMDailyTransaction.objects.filter(terminal_number_snapshot="").count(),
        }
        self.stdout.write(json.dumps(payload, indent=2))
