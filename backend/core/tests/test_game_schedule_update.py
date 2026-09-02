from datetime import date, time
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.game_schedule import APPROVED_WEEKLY_GAME_NAMES, APPROVED_WEEKLY_SCHEDULE, apply_approved_weekly_game_schedule
from core.models import Agency, AuditAction, AuditLog, DailySheet, Game, UserAgencyAssignment, Weekday, WeeklyGameSchedule


User = get_user_model()


def active_schedule(weekday):
    return list(
        WeeklyGameSchedule.objects.filter(weekday=weekday, is_active=True, game__is_active=True)
        .select_related("game")
        .order_by("display_order", "id")
    )


def schedule_tuple(schedule):
    return (
        schedule.game.name,
        schedule.display_order,
        schedule.is_whole_day,
        schedule.closing_time,
        schedule.draw_time,
    )


class ApprovedGameScheduleTests(TestCase):
    def test_exact_ordered_schedule_for_all_weekdays(self):
        call_command("seed_initial_data", stdout=StringIO())

        for weekday, names in APPROVED_WEEKLY_GAME_NAMES.items():
            self.assertEqual([row.game.name for row in active_schedule(weekday)], names)

    def test_known_game_day_times_and_whole_day_entries(self):
        call_command("seed_initial_data", stdout=StringIO())

        for entry in APPROVED_WEEKLY_SCHEDULE:
            row = WeeklyGameSchedule.objects.get(weekday=entry.weekday, game__name=entry.game_name, is_active=True)
            self.assertEqual(schedule_tuple(row), (entry.game_name, entry.display_order, entry.is_whole_day, entry.closing_time, entry.draw_time))

    def test_all_whole_day_entries_have_null_times(self):
        call_command("seed_initial_data", stdout=StringIO())

        whole_day_names = list(
            WeeklyGameSchedule.objects.filter(is_active=True, is_whole_day=True)
            .order_by("weekday", "display_order")
            .values_list("game__name", flat=True)
        )

        self.assertEqual(whole_day_names, ["Monday Special", "Lucky G", "Midweek", "Lucky", "Fortune", "Bonanza", "National", "Aseda"])
        self.assertFalse(WeeklyGameSchedule.objects.filter(is_whole_day=True, closing_time__isnull=False).exists())
        self.assertFalse(WeeklyGameSchedule.objects.filter(is_whole_day=True, draw_time__isnull=False).exists())

    def test_whole_day_requires_null_times_and_timed_requires_both_times(self):
        game = Game.objects.create(name="Validation Game")

        with self.assertRaises(ValidationError):
            WeeklyGameSchedule.objects.create(game=game, weekday=Weekday.MONDAY, is_whole_day=True, closing_time=time(10), draw_time=time(11), display_order=1)

        with self.assertRaises(ValidationError):
            WeeklyGameSchedule.objects.create(game=game, weekday=Weekday.MONDAY, is_whole_day=False, display_order=1)

    def test_partial_time_input_rejected(self):
        game = Game.objects.create(name="Partial Time")

        with self.assertRaises(ValidationError):
            WeeklyGameSchedule.objects.create(game=game, weekday=Weekday.MONDAY, closing_time=time(10), display_order=1)

        with self.assertRaises(ValidationError):
            WeeklyGameSchedule.objects.create(game=game, weekday=Weekday.MONDAY, draw_time=time(11), display_order=1)

    def test_repeated_seed_is_idempotent(self):
        call_command("seed_initial_data", stdout=StringIO())
        first_counts = (Game.objects.count(), WeeklyGameSchedule.objects.count())
        call_command("seed_initial_data", stdout=StringIO())
        second_counts = (Game.objects.count(), WeeklyGameSchedule.objects.count())

        self.assertEqual(first_counts, second_counts)
        self.assertEqual(WeeklyGameSchedule.objects.filter(is_active=True).count(), 41)

    def test_no_duplicate_active_game_day_schedule(self):
        game = Game.objects.create(name="Duplicate Game")
        WeeklyGameSchedule.objects.create(game=game, weekday=Weekday.MONDAY, closing_time=time(10), draw_time=time(11), display_order=1)

        with self.assertRaises((IntegrityError, ValidationError)), transaction.atomic():
            WeeklyGameSchedule.objects.create(game=game, weekday=Weekday.MONDAY, closing_time=time(12), draw_time=time(13), display_order=2)

    def test_new_sheet_snapshots_whole_day_status(self):
        agency = Agency.objects.create(name="Musa 1", code="musa-1")
        user = User.objects.create_user("acct@example.com", "pass-12345", full_name="Acct")
        call_command("seed_initial_data", stdout=StringIO())

        sheet = DailySheet.objects.create(agency=agency, transaction_date=date(2026, 8, 24), created_by=user)
        sheet.copy_weekday_games()

        monday_special = sheet.sheet_games.get(game_name_snapshot="Monday Special")
        self.assertTrue(monday_special.is_whole_day_snapshot)
        self.assertIsNone(monday_special.closing_time_snapshot)
        self.assertIsNone(monday_special.draw_time_snapshot)

    def test_old_daily_sheet_snapshots_are_not_modified_after_schedule_edits(self):
        agency = Agency.objects.create(name="Musa 1", code="musa-1")
        user = User.objects.create_user("acct@example.com", "pass-12345", full_name="Acct")
        call_command("seed_initial_data", stdout=StringIO())
        sheet = DailySheet.objects.create(agency=agency, transaction_date=date(2026, 8, 24), created_by=user)
        sheet.copy_weekday_games()
        snapshot = sheet.sheet_games.get(game_name_snapshot="Peoples")

        schedule = WeeklyGameSchedule.objects.get(weekday=Weekday.MONDAY, game__name="Peoples", is_active=True)
        schedule.is_whole_day = True
        schedule.closing_time = None
        schedule.draw_time = None
        schedule.save()
        snapshot.refresh_from_db()

        self.assertFalse(snapshot.is_whole_day_snapshot)
        self.assertEqual(snapshot.closing_time_snapshot, time(12, 30))
        self.assertEqual(snapshot.draw_time_snapshot, time(12, 45))

    def test_canonical_naming_and_06_string_preservation(self):
        Game.objects.create(name="MSP")
        Game.objects.create(name="MK II")
        Game.objects.create(name="C/Master")

        apply_approved_weekly_game_schedule()

        self.assertTrue(Game.objects.filter(name="Monday Special").exists())
        self.assertTrue(Game.objects.filter(name="Mark II").exists())
        self.assertTrue(Game.objects.filter(name="Club Master").exists())
        game = Game.objects.get(name="06")
        self.assertIsInstance(game.name, str)
        self.assertEqual(game.name, "06")
        self.assertEqual(active_schedule(Weekday.WEDNESDAY).count(WeeklyGameSchedule.objects.get(weekday=Weekday.WEDNESDAY, game__name="Midweek")), 1)
        self.assertEqual(active_schedule(Weekday.THURSDAY).count(WeeklyGameSchedule.objects.get(weekday=Weekday.THURSDAY, game__name="Fortune")), 1)


class WeeklyGameScheduleAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin@example.com", "pass-12345", full_name="Admin")
        self.accountant = User.objects.create_user("acct@example.com", "pass-12345", full_name="Acct")
        self.agency = Agency.objects.create(name="Musa 1", code="musa-1")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True)
        call_command("seed_initial_data", stdout=StringIO())

    def test_super_admin_create_edit_activate_deactivate_and_audit(self):
        self.client.force_authenticate(self.admin)
        game = Game.objects.create(name="API Game")

        created = self.client.post(
            "/api/weekly-game-schedules/",
            {"game": game.id, "weekday": Weekday.SUNDAY, "display_order": 9, "is_whole_day": True, "closing_time": None, "draw_time": None, "is_active": False},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        schedule_id = created.data["id"]

        updated = self.client.patch(
            f"/api/weekly-game-schedules/{schedule_id}/",
            {"is_whole_day": False, "closing_time": "08:00", "draw_time": "08:30", "is_active": True},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertFalse(updated.data["is_whole_day"])

        deactivated = self.client.delete(f"/api/weekly-game-schedules/{schedule_id}/")
        self.assertEqual(deactivated.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WeeklyGameSchedule.objects.get(pk=schedule_id).is_active)
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.SCHEDULE_CREATED, object_id=str(schedule_id)).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.SCHEDULE_ACTIVATED, object_id=str(schedule_id)).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditAction.SCHEDULE_DEACTIVATED, object_id=str(schedule_id)).exists())

    def test_accountant_mutation_denied_but_schedule_read_allowed(self):
        self.client.force_authenticate(self.accountant)
        game = Game.objects.create(name="Blocked API Game")

        read = self.client.get("/api/weekly-game-schedules/?weekday=1&active=true")
        create = self.client.post(
            "/api/weekly-game-schedules/",
            {"game": game.id, "weekday": Weekday.MONDAY, "display_order": 9, "is_whole_day": True},
            format="json",
        )

        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual([item["game_name"] for item in read.data], APPROVED_WEEKLY_GAME_NAMES[Weekday.MONDAY])
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_rejects_duplicate_and_invalid_values(self):
        self.client.force_authenticate(self.admin)
        peoples = Game.objects.get(name="Peoples")

        duplicate = self.client.post(
            "/api/weekly-game-schedules/",
            {"game": peoples.id, "weekday": Weekday.MONDAY, "display_order": 9, "is_whole_day": True},
            format="json",
        )
        invalid_weekday = self.client.post(
            "/api/weekly-game-schedules/",
            {"game": peoples.id, "weekday": 9, "display_order": 9, "is_whole_day": True},
            format="json",
        )
        partial_time = self.client.post(
            "/api/weekly-game-schedules/",
            {"game": peoples.id, "weekday": Weekday.SUNDAY, "display_order": 9, "is_whole_day": False, "closing_time": "08:00"},
            format="json",
        )

        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid_weekday.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(partial_time.status_code, status.HTTP_400_BAD_REQUEST)

    def test_games_for_date_and_new_sheet_use_current_schedule(self):
        self.client.force_authenticate(self.accountant)

        schedule = self.client.get("/api/games/for-date/?date=2026-08-24")
        sheet = self.client.post(
            "/api/daily-sheets/",
            {"agency": self.agency.id, "transaction_date": "2026-08-24", "incoming_funds": "0.00", "tax": "0.00"},
            format="json",
        )

        self.assertEqual(schedule.status_code, status.HTTP_200_OK)
        self.assertEqual([item["game_name"] for item in schedule.data], APPROVED_WEEKLY_GAME_NAMES[Weekday.MONDAY])
        self.assertEqual(sheet.status_code, status.HTTP_201_CREATED)
        monday_special = [item for item in sheet.data["sheet_games"] if item["game_name_snapshot"] == "Monday Special"][0]
        self.assertTrue(monday_special["is_whole_day_snapshot"])
        self.assertIsNone(monday_special["closing_time_snapshot"])
