from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITransactionTestCase

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


def game_on_whole_day(weekday, name):
    return Game.objects.get(
        name=name,
        weekly_schedules__weekday=weekday,
        weekly_schedules__is_whole_day=True,
        weekly_schedules__is_active=True,
    )


class CorrectedWednesdayScheduleTests(TestCase):
    def test_wednesday_has_seven_games_and_two_whole_day_categories(self):
        call_command("seed_initial_data", verbosity=0)
        validate_active_weekly_game_schedule()

        rows = list(
            WeeklyGameSchedule.objects.filter(
                weekday=Weekday.WEDNESDAY, is_active=True, game__is_active=True,
            ).select_related("game").order_by("display_order")
        )
        self.assertEqual(len(rows), 7)
        self.assertEqual([row.game.name for row in rows if row.is_whole_day], ["Midweek", "Double Chance"])
        lucky = next(row for row in rows if row.game.name == "Lucky")
        self.assertFalse(lucky.is_whole_day)
        self.assertEqual(lucky.closing_time.isoformat(), "22:30:00")
        self.assertEqual(lucky.draw_time.isoformat(), "22:45:00")


class HolidayGameOverrideAPITests(APITransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("holiday-admin@example.com", "pass-12345", full_name="Holiday Admin")
        self.accountant = User.objects.create_user("holiday-accountant@example.com", "pass-12345", full_name="Holiday Accountant")
        self.agency = Agency.objects.create(name="Holiday Agency", code="holiday-agency")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True, can_edit=True)
        call_command("seed_initial_data", verbosity=0)
        self.normal_game = game_on_whole_day(Weekday.MONDAY, "MSP")
        self.previous_game = game_on_whole_day(Weekday.FRIDAY, "Bonanza")
        today = timezone.localdate()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        days_since_friday = (today.weekday() - 4) % 7
        self.holiday_date = today + timedelta(days=days_until_monday)
        self.source_date = today - timedelta(days=days_since_friday)

    def payload(self, **updates):
        return {
            "holiday_date": self.holiday_date.isoformat(),
            "holiday_name": "Founders Day",
            "normal_game": self.normal_game.id,
            "replacement_game": self.previous_game.id,
            "source_date": self.source_date.isoformat(),
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

        read = self.client.get(f"/api/holiday-game-overrides/?holiday_date={self.holiday_date.isoformat()}")
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
            {"holiday_date": self.holiday_date.isoformat(), "holiday_name": "Founders Day"},
            format="json",
        )
        future_holiday_date = self.holiday_date + timedelta(days=7)
        future_source = self.client.post(
            "/api/holiday-game-overrides/",
            self.payload(
                holiday_date=future_holiday_date.isoformat(),
                source_date=(timezone.localdate() + timedelta(days=1)).isoformat(),
            ),
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

    def test_past_holiday_date_is_rejected(self):
        self.client.force_authenticate(self.admin)
        days_since_monday = timezone.localdate().weekday() or 7
        past_holiday_date = timezone.localdate() - timedelta(days=days_since_monday)
        response = self.client.post(
            "/api/holiday-game-overrides/",
            self.payload(
                holiday_date=past_holiday_date.isoformat(),
                source_date=(past_holiday_date - timedelta(days=3)).isoformat(),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("future", str(response.data).lower())

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

        self.assertEqual(edited.status_code, status.HTTP_200_OK, edited.data)
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
            {"agency": self.agency.id, "transaction_date": self.holiday_date.isoformat()},
            format="json",
        )
        self.assertEqual(normal_sheet_response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(normal_sheet_response.data["holiday_override_applied"])
        self.assertIn("MSP", [row["game_name_snapshot"] for row in normal_sheet_response.data["sheet_games"]])

        second_agency = Agency.objects.create(name="Holiday Agency 2", code="holiday-agency-2")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=second_agency, can_create=True)
        self.client.force_authenticate(self.admin)
        override = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        self.assertEqual(override.status_code, status.HTTP_201_CREATED, override.data)

        self.client.force_authenticate(self.accountant)
        holiday_sheet_response = self.client.post(
            "/api/daily-sheets/",
            {"agency": second_agency.id, "transaction_date": self.holiday_date.isoformat()},
            format="json",
        )
        self.assertEqual(holiday_sheet_response.status_code, status.HTTP_201_CREATED, holiday_sheet_response.data)
        sheet_data = holiday_sheet_response.data
        names = [row["game_name_snapshot"] for row in sheet_data["sheet_games"]]
        self.assertTrue(sheet_data["holiday_override_applied"])
        self.assertEqual(sheet_data["holiday_name_snapshot"], "Founders Day")
        self.assertEqual(sheet_data["holiday_source_date_snapshot"], self.source_date.isoformat())
        self.assertEqual(len(names), 7)
        self.assertIn("Double Chance", names)
        dc = next(row for row in sheet_data["sheet_games"] if row["category_snapshot"] == "DOUBLE_CHANCE")
        self.assertFalse(dc["is_holiday_override_snapshot"])
        self.assertIn("Bonanza", names)
        self.assertNotIn("MSP", names)
        replacement = next(row for row in sheet_data["sheet_games"] if row["game_name_snapshot"] == "Bonanza")
        self.assertTrue(replacement["is_holiday_override_snapshot"])
        self.assertTrue(replacement["is_whole_day_snapshot"])
        self.assertIn("Peoples", names)
        self.assertEqual(next(row for row in sheet_data["sheet_games"] if row["game_name_snapshot"] == "Peoples")["closing_time_snapshot"], "12:30:00")

    def test_deactivation_does_not_rewrite_existing_sheet_snapshots(self):
        self.client.force_authenticate(self.admin)
        override_data = self.create_override()
        second_agency = Agency.objects.create(name="Holiday Agency 2", code="holiday-agency-2")
        sheet = DailySheet.objects.create(agency=second_agency, transaction_date=self.holiday_date, created_by=self.accountant)
        sheet.copy_weekday_games()
        before = list(sheet.sheet_games.values_list("game_name_snapshot", "is_holiday_override_snapshot", "closing_time_snapshot"))

        deactivated = self.client.patch(
            f"/api/holiday-game-overrides/{override_data['id']}/",
            {"is_active": False},
            format="json",
        )
        sheet.refresh_from_db()
        after = list(sheet.sheet_games.values_list("game_name_snapshot", "is_holiday_override_snapshot", "closing_time_snapshot"))
        later_sheet = DailySheet.objects.create(agency=self.agency, transaction_date=self.holiday_date, created_by=self.accountant)
        later_sheet.copy_weekday_games()

        self.assertEqual(deactivated.status_code, status.HTTP_200_OK)
        self.assertTrue(sheet.holiday_override_applied)
        self.assertEqual(before, after)
        self.assertFalse(later_sheet.holiday_override_applied)
        self.assertTrue(later_sheet.sheet_games.filter(game_name_snapshot="MSP").exists())

    def test_used_override_cannot_be_edited(self):
        self.client.force_authenticate(self.admin)
        override_data = self.create_override()
        sheet = DailySheet.objects.create(agency=self.agency, transaction_date=self.holiday_date, created_by=self.admin)
        sheet.copy_weekday_games()

        response = self.client.patch(
            f"/api/holiday-game-overrides/{override_data['id']}/",
            {"holiday_name": "Changed after use"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(HolidayGameOverride.objects.get(pk=override_data["id"]).holiday_name, "Founders Day")

    def test_active_override_blocks_game_rename_and_ghana_category_change(self):
        self.client.force_authenticate(self.admin)
        override = self.create_override()
        rename = self.client.patch(
            f"/api/games/{self.normal_game.pk}/",
            {"name": "Renamed Ghana game"},
            format="json",
        )
        schedule = WeeklyGameSchedule.objects.get(
            game=self.normal_game, weekday=self.holiday_date.isoweekday(), is_active=True,
        )
        category_change = self.client.patch(
            f"/api/weekly-game-schedules/{schedule.pk}/",
            {
                "category": "TIMED",
                "is_whole_day": False,
                "closing_time": "08:00",
                "draw_time": "08:30",
            },
            format="json",
        )
        self.assertEqual(rename.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", rename.data)
        self.assertEqual(category_change.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", category_change.data)
        self.assertTrue(HolidayGameOverride.objects.filter(pk=override["id"], is_active=True).exists())
        self.assertEqual(Game.objects.get(pk=self.normal_game.pk).name, "MSP")
    def test_double_chance_cannot_be_holiday_normal_or_replacement(self):
        self.client.force_authenticate(self.admin)
        double = Game.objects.get(name="Double Chance")
        for field in ("normal_game", "replacement_game"):
            response = self.client.post("/api/holiday-game-overrides/", self.payload(**{field: double.pk}), format="json")
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)

    def test_holiday_excel_preview_and_confirmation_share_effective_categories(self):
        from core.models import Person, TPMCode
        from core.tests.test_daily_sheet_imports import workbook_upload
        from core.holiday_overrides import effective_schedule_for_date
        self.client.force_authenticate(self.admin)
        override = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        self.assertEqual(override.status_code, 201)
        person = Person.objects.create(agency=self.agency, full_name="Holiday importer", agent_type="SUBAGENT")
        code = TPMCode.objects.create(person=person, code="HOLIDAY-IMPORT")
        schedule, _ = effective_schedule_for_date(self.holiday_date)
        headers = [row.game.name for row in schedule]
        preview = self.client.post("/api/daily-sheet-imports/preview/", {
            "agency": self.agency.pk, "transaction_date": self.holiday_date.isoformat(),
            "file": workbook_upload(headers=headers, raw_date=self.holiday_date,
                rows=[{"sub": "HOLIDAY", "amounts": [10] * 7}], register_rows=[("HOLIDAY", code.code, person.full_name)]),
        }, format="multipart")
        self.assertEqual(preview.status_code, 201, preview.data)
        self.assertEqual(preview.data["errors"], [])
        confirm = self.client.post(f"/api/daily-sheet-imports/{preview.data['id']}/confirm/", {}, format="json")
        self.assertEqual(confirm.status_code, 200, confirm.data)
        sheet = DailySheet.objects.get(pk=confirm.data["daily_sheet"])
        self.assertEqual(sheet.sheet_games.get(category_snapshot="GHANA").game_name_snapshot, "Bonanza")
        self.assertTrue(sheet.sheet_games.filter(category_snapshot="DOUBLE_CHANCE").exists())

    def test_legacy_override_game_reference_still_applies_without_rewriting_it(self):
        from core.holiday_overrides import effective_schedule_for_date
        from core.tests.test_game_categories import migrate_schedule
        self.client.force_authenticate(self.admin)
        response = self.client.post("/api/holiday-game-overrides/", self.payload(), format="json")
        legacy = Game.objects.create(name="Monday Special")
        HolidayGameOverride.objects.filter(pk=response.data["id"]).update(normal_game=legacy)
        before = HolidayGameOverride.objects.values().get(pk=response.data["id"])
        migrate_schedule()
        rows, override = effective_schedule_for_date(self.holiday_date)
        self.assertEqual([r.game.name for r in rows if r.category == "GHANA"], ["Bonanza"])
        self.assertEqual(HolidayGameOverride.objects.values().get(pk=override.pk), before)
        cancelled = self.client.post(f"/api/holiday-game-overrides/{override.pk}/cancel/", {"reason": "Cancelled holiday"}, format="json")
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
