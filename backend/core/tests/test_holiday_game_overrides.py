from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.game_schedule import validate_active_weekly_game_schedule
from core.models import (
    Agency,
    AuditAction,
    AuditLog,
    DailySheet,
    Game,
    HolidayGameOverride,
    UserAgencyAssignment,
    Weekday,
    WeeklyGameSchedule,
)


User = get_user_model()
HOLIDAY_DATE = date(2026, 9, 28)
SOURCE_DATE = date(2026, 9, 25)


def game_on_whole_day(weekday, name):
    return Game.objects.get(
        name=name,
        weekly_schedules__weekday=weekday,
        weekly_schedules__is_whole_day=True,
        weekly_schedules__is_active=True,
    )


class CorrectedWednesdayScheduleTests(TestCase):
    def test_wednesday_has_six_games_and_only_midweek_is_whole_day(self):
        call_command("seed_initial_data", verbosity=0)
        validate_active_weekly_game_schedule()

        rows = list(
            WeeklyGameSchedule.objects.filter(
                weekday=Weekday.WEDNESDAY, is_active=True, game__is_active=True,
            ).select_related("game").order_by("display_order")
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual([row.game.name for row in rows if row.is_whole_day], ["Midweek"])
        lucky = next(row for row in rows if row.game.name == "Lucky")
        self.assertFalse(lucky.is_whole_day)
        self.assertEqual(lucky.closing_time.isoformat(), "22:30:00")
        self.assertEqual(lucky.draw_time.isoformat(), "22:45:00")


class HolidayGameOverrideAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("holiday-admin@example.com", "pass-12345", full_name="Holiday Admin")
        self.accountant = User.objects.create_user("holiday-accountant@example.com", "pass-12345", full_name="Holiday Accountant")
        self.agency = Agency.objects.create(name="Holiday Agency", code="holiday-agency")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True, can_edit=True)
        call_command("seed_initial_data", verbosity=0)
        self.normal_game = game_on_whole_day(Weekday.MONDAY, "Monday Special")
        self.previous_game = game_on_whole_day(Weekday.FRIDAY, "Bonanza")

    def payload(self, **updates):
        return {
            "holiday_date": HOLIDAY_DATE.isoformat(),
            "holiday_name": "Founders Day",
            "normal_game": self.normal_game.id,
            "replacement_game": self.previous_game.id,
            "source_date": SOURCE_DATE.isoformat(),
            "notes": "private-note-marker",
            "is_active": True,
            **updates,
        }

    def create_override(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def test_accountant_can_view_but_cannot_mutate_overrides(self):
        self.create_override()
        self.client.force_authenticate(self.accountant)

        read = self.client.get(f"/api/holiday-game-overrides/?holiday_date={HOLIDAY_DATE.isoformat()}")
        create = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        update = self.client.patch(f"/api/holiday-game-overrides/{read.data[0]['id']}/", {"is_active": False}, format="json")

        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual(read.data[0]["replacement_game_name"], "Bonanza")
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update.status_code, status.HTTP_403_FORBIDDEN)

    def test_requires_explicit_games_and_rejects_future_source_date(self):
        self.client.force_authenticate(self.admin)
        missing = self.client.post(
            "/api/holiday-game-overrides/",
            {"holiday_date": HOLIDAY_DATE.isoformat(), "holiday_name": "Founders Day"},
            format="json",
        )
        future_source = self.client.post(
            "/api/holiday-game-overrides/",
            self.payload(holiday_date=date(2026, 10, 5).isoformat(), source_date=date(2026, 10, 2).isoformat()),
            format="json",
        )
        timed_replacement = self.client.post(
            "/api/holiday-game-overrides/",
            self.payload(replacement_game=Game.objects.get(name="Royal").id),
            format="json",
        )

        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(future_source.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("future", str(future_source.data).lower())
        self.assertEqual(timed_replacement.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_active_holiday_date_is_rejected(self):
        self.client.force_authenticate(self.admin)
        first = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        duplicate = self.client.post(
            "/api/holiday-game-overrides/",
            self.payload(holiday_name="Second holiday"),
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

    def test_super_admin_lifecycle_audits_without_free_text(self):
        self.client.force_authenticate(self.admin)
        created = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        override_id = created.data["id"]

        edited = self.client.patch(
            f"/api/holiday-game-overrides/{override_id}/",
            {"holiday_name": "Founders Day Observed"},
            format="json",
        )
        inactive = self.client.patch(f"/api/holiday-game-overrides/{override_id}/", {"is_active": False}, format="json")
        active = self.client.patch(f"/api/holiday-game-overrides/{override_id}/", {"is_active": True}, format="json")
        missing_reason = self.client.post(f"/api/holiday-game-overrides/{override_id}/cancel/", {}, format="json")
        cancelled = self.client.post(
            f"/api/holiday-game-overrides/{override_id}/cancel/",
            {"reason": "private-cancellation-marker"},
            format="json",
        )

        self.assertEqual(edited.status_code, status.HTTP_200_OK)
        self.assertEqual(inactive.status_code, status.HTTP_200_OK)
        self.assertEqual(active.status_code, status.HTTP_200_OK)
        self.assertEqual(missing_reason.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertFalse(cancelled.data["is_active"])
        self.assertTrue(cancelled.data["cancelled_at"])
        actions = set(AuditLog.objects.filter(model_name="HolidayGameOverride").values_list("action", flat=True))
        self.assertEqual(actions, {
            AuditAction.HOLIDAY_OVERRIDE_CREATED,
            AuditAction.HOLIDAY_OVERRIDE_UPDATED,
            AuditAction.HOLIDAY_OVERRIDE_ACTIVATED,
            AuditAction.HOLIDAY_OVERRIDE_DEACTIVATED,
            AuditAction.HOLIDAY_OVERRIDE_CANCELLED,
        })
        audit_text = " ".join(str(item) for item in AuditLog.objects.filter(model_name="HolidayGameOverride").values_list("old_values", "new_values", "description"))
        self.assertNotIn("private-note-marker", audit_text)
        self.assertNotIn("private-cancellation-marker", audit_text)

    def test_normal_schedule_without_override_and_override_snapshot_with_timed_games(self):
        self.client.force_authenticate(self.accountant)
        normal_sheet_response = self.client.post(
            "/api/daily-sheets/",
            {"agency": self.agency.id, "transaction_date": HOLIDAY_DATE.isoformat()},
            format="json",
        )
        self.assertEqual(normal_sheet_response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(normal_sheet_response.data["holiday_override_applied"])
        self.assertIn("Monday Special", [row["game_name_snapshot"] for row in normal_sheet_response.data["sheet_games"]])

        second_agency = Agency.objects.create(name="Holiday Agency 2", code="holiday-agency-2")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=second_agency, can_create=True)
        self.client.force_authenticate(self.admin)
        override = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        self.assertEqual(override.status_code, status.HTTP_201_CREATED, override.data)

        self.client.force_authenticate(self.accountant)
        holiday_sheet_response = self.client.post(
            "/api/daily-sheets/",
            {"agency": second_agency.id, "transaction_date": HOLIDAY_DATE.isoformat()},
            format="json",
        )
        self.assertEqual(holiday_sheet_response.status_code, status.HTTP_201_CREATED, holiday_sheet_response.data)
        sheet_data = holiday_sheet_response.data
        names = [row["game_name_snapshot"] for row in sheet_data["sheet_games"]]
        self.assertTrue(sheet_data["holiday_override_applied"])
        self.assertEqual(sheet_data["holiday_name_snapshot"], "Founders Day")
        self.assertEqual(sheet_data["holiday_source_date_snapshot"], SOURCE_DATE.isoformat())
        self.assertIn("Bonanza", names)
        self.assertNotIn("Monday Special", names)
        replacement = next(row for row in sheet_data["sheet_games"] if row["game_name_snapshot"] == "Bonanza")
        self.assertTrue(replacement["is_holiday_override_snapshot"])
        self.assertTrue(replacement["is_whole_day_snapshot"])
        self.assertIn("Peoples", names)
        self.assertEqual(next(row for row in sheet_data["sheet_games"] if row["game_name_snapshot"] == "Peoples")["closing_time_snapshot"], "12:30:00")

    def test_deactivation_does_not_rewrite_existing_sheet_snapshots(self):
        self.client.force_authenticate(self.admin)
        override_data = self.create_override()
        second_agency = Agency.objects.create(name="Holiday Agency 2", code="holiday-agency-2")
        sheet = DailySheet.objects.create(agency=second_agency, transaction_date=HOLIDAY_DATE, created_by=self.accountant)
        sheet.copy_weekday_games()
        before = list(sheet.sheet_games.values_list("game_name_snapshot", "is_holiday_override_snapshot", "closing_time_snapshot"))

        deactivated = self.client.patch(
            f"/api/holiday-game-overrides/{override_data['id']}/",
            {"is_active": False},
            format="json",
        )
        sheet.refresh_from_db()
        after = list(sheet.sheet_games.values_list("game_name_snapshot", "is_holiday_override_snapshot", "closing_time_snapshot"))
        later_sheet = DailySheet.objects.create(agency=self.agency, transaction_date=HOLIDAY_DATE, created_by=self.accountant)
        later_sheet.copy_weekday_games()

        self.assertEqual(deactivated.status_code, status.HTTP_200_OK)
        self.assertTrue(sheet.holiday_override_applied)
        self.assertEqual(before, after)
        self.assertFalse(later_sheet.holiday_override_applied)
        self.assertTrue(later_sheet.sheet_games.filter(game_name_snapshot="Monday Special").exists())

    def test_used_override_cannot_be_edited(self):
        self.client.force_authenticate(self.admin)
        override_data = self.create_override()
        sheet = DailySheet.objects.create(agency=self.agency, transaction_date=HOLIDAY_DATE, created_by=self.admin)
        sheet.copy_weekday_games()

        response = self.client.patch(
            f"/api/holiday-game-overrides/{override_data['id']}/",
            {"holiday_name": "Changed after use"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(HolidayGameOverride.objects.get(pk=override_data["id"]).holiday_name, "Founders Day")