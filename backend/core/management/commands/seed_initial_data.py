from datetime import time

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.models import Agency, Game, Weekday, WeeklyGameSchedule


class Command(BaseCommand):
    help = "Seed initial agencies and weekly game schedules."

    agencies = ["Musa 1", "Musa 2", "Omolade", "Treasure Land", "Sango"]
    schedule = {
        Weekday.MONDAY: [
            ("Diamond", "09:00", "09:45"),
            ("Peoples", "12:30", "12:45"),
            ("Bingo", "15:30", "15:45"),
            ("Metro", "19:30", "19:45"),
            ("International", "22:30", "22:45"),
        ],
        Weekday.TUESDAY: [
            ("Gold", "09:00", "09:45"),
            ("06", "12:30", "12:45"),
            ("Jackpot", "15:30", "15:45"),
            ("Club Master", "19:30", "19:45"),
            ("Super", "22:30", "22:45"),
        ],
        Weekday.WEDNESDAY: [
            ("Tota", "09:00", "09:45"),
            ("MK II", "12:30", "12:45"),
            ("VAG", "15:30", "15:45"),
            ("Enugu", "19:30", "19:45"),
        ],
        Weekday.THURSDAY: [
            ("Peoples", "09:00", "09:45"),
            ("Fairchance", "12:30", "13:30"),
            ("Diamond", "15:30", "15:45"),
            ("International", "19:30", "19:45"),
            ("Bingo", "22:30", "22:45"),
        ],
        Weekday.FRIDAY: [
            ("Royal", "09:00", "09:45"),
            ("Metro", "12:30", "12:45"),
            ("Gold", "15:30", "15:45"),
            ("Jackpot", "19:30", "19:45"),
            ("VAG", "22:30", "22:45"),
        ],
        Weekday.SATURDAY: [
            ("King", "09:30", "09:45"),
            ("Super", "12:30", "12:45"),
            ("Club Master", "15:30", "15:45"),
            ("06", "19:30", "19:45"),
            ("Fairchance", "22:00", "22:30"),
        ],
        Weekday.SUNDAY: [
            ("MK II", "12:30", "12:45"),
            ("Enugu", "15:30", "15:45"),
            ("Lucky", "19:30", "19:45"),
            ("Tota", "21:30", "21:45"),
        ],
    }

    def handle(self, *args, **options):
        for agency_name in self.agencies:
            Agency.objects.update_or_create(
                name=agency_name,
                defaults={"code": slugify(agency_name), "is_active": True},
            )

        for weekday, rows in self.schedule.items():
            for display_order, (game_name, closing_time, draw_time) in enumerate(rows, start=1):
                game, _ = Game.objects.update_or_create(name=game_name, defaults={"is_active": True})
                WeeklyGameSchedule.objects.update_or_create(
                    game=game,
                    weekday=weekday,
                    is_active=True,
                    defaults={
                        "closing_time": self.parse_time(closing_time),
                        "draw_time": self.parse_time(draw_time),
                        "display_order": display_order,
                    },
                )

        self.stdout.write(self.style.SUCCESS("Initial data seeded successfully."))

    @staticmethod
    def parse_time(value):
        hour, minute = value.split(":")
        return time(hour=int(hour), minute=int(minute))
