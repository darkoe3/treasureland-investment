from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.game_schedule import apply_approved_weekly_game_schedule
from core.models import Agency


class Command(BaseCommand):
    help = "Seed initial agencies and weekly game schedules."

    agencies = ["Musa 1", "Musa 2", "Omolade", "Treasure Land", "Sango"]
    def handle(self, *args, **options):
        for agency_name in self.agencies:
            Agency.objects.update_or_create(
                name=agency_name,
                defaults={"code": slugify(agency_name), "is_active": True},
            )

        apply_approved_weekly_game_schedule()

        self.stdout.write(self.style.SUCCESS("Initial data seeded successfully."))
