from datetime import date, time
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.game_schedule import APPROVED_WEEKLY_GAME_NAMES
from core.models import (
    Agency,
    AuditAction,
    AuditLog,
    DailySheet,
    DailySheetGame,
    Game,
    UserAgencyAssignment,
    Weekday,
    WeeklyGameSchedule,
)


User = get_user_model()


class GameCatalogueAPITests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", stdout=StringIO())
        self.admin = User.objects.create_superuser("catalogue-admin@example.com", "pass-12345", full_name="Admin")
        self.accountant = User.objects.create_user("catalogue-accountant@example.com", "pass-12345", full_name="Accountant")

    def test_game_catalogue_contract_and_write_permissions(self):
        self.client.force_authenticate(self.accountant)
        read = self.client.get("/api/games/")
        rows = read.data.get("results", read.data) if isinstance(read.data, dict) else read.data
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertTrue(rows)
        self.assertEqual(
            set(rows[0]),
            {"id", "name", "category", "is_active", "created_at", "updated_at"},
        )
        self.assertTrue(rows[0]["created_at"])
        self.assertTrue(rows[0]["updated_at"])
        self.assertEqual(
            self.client.post("/api/games/", {"name": "Blocked"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        game = Game.objects.create(name="Accountant edit")
        self.assertEqual(
            self.client.patch(f"/api/games/{game.pk}/", {"name": "Blocked"}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.delete(f"/api/games/{game.pk}/").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        game.refresh_from_db()
        self.assertTrue(game.is_active)

    def test_super_admin_create_update_name_normalization_and_audit(self):
        self.client.force_authenticate(self.admin)
        created = self.client.post("/api/games/", {"name": "  Catalogue New  "}, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertEqual(created.data["name"], "Catalogue New")
        self.assertEqual(
            set(created.data),
            {"id", "name", "category", "is_active", "created_at", "updated_at"},
        )
        game_id = created.data["id"]
        edited = self.client.patch(f"/api/games/{game_id}/", {"name": "  Renamed Game  "}, format="json")
        duplicate = self.client.post("/api/games/", {"name": "  renamed game "}, format="json")
        blank = self.client.post("/api/games/", {"name": "   "}, format="json")
        self.assertEqual(edited.status_code, status.HTTP_200_OK, edited.data)
        self.assertEqual(edited.data["name"], "Renamed Game")
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(blank.status_code, status.HTTP_400_BAD_REQUEST)
        audits = AuditLog.objects.filter(model_name="Game", object_id=str(game_id))
        self.assertEqual(
            set(audits.values_list("action", flat=True)),
            {AuditAction.GAME_CREATED, AuditAction.GAME_UPDATED},
        )
        audit_text = " ".join(
            str(values)
            for values in audits.values_list("old_values", "new_values", "description")
        )
        self.assertNotIn("Catalogue New", audit_text)
        self.assertNotIn("Renamed Game", audit_text)

    def test_create_supports_each_category_and_normalizes_ghana_alias(self):
        self.client.force_authenticate(self.admin)
        for index, (category, expected) in enumerate((
            ("TIMED", "TIMED"),
            ("GHANA_GAME", "GHANA"),
            ("DOUBLE_CHANCE", "DOUBLE_CHANCE"),
        )):
            response = self.client.post(
                "/api/games/",
                {"name": f"Category {index}", "category": category},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
            self.assertEqual(response.data["category"], expected)

    def test_named_ghana_game_is_always_timed(self):
        self.client.force_authenticate(self.admin)
        for category in ("GHANA", "GHANA_GAME"):
            with self.subTest(category=category):
                rejected = self.client.post(
                    "/api/games/",
                    {"name": "Ghana Game", "category": category},
                    format="json",
                )
                self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("category", rejected.data)

        whole_day_game = Game.objects.create(name="Whole Day Source", category="GHANA")
        renamed = self.client.patch(
            f"/api/games/{whole_day_game.pk}/",
            {"name": "Ghana Game"},
            format="json",
        )
        self.assertEqual(renamed.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", renamed.data)

        created = self.client.post(
            "/api/games/",
            {"name": " Ghana Game ", "category": "TIMED"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertEqual(created.data["category"], "TIMED")

        changed = self.client.patch(
            f"/api/games/{created.data['id']}/",
            {"category": "GHANA"},
            format="json",
        )
        self.assertEqual(changed.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", changed.data)
        game = Game.objects.get(pk=created.data["id"])
        self.assertEqual(game.category, "TIMED")

    def test_category_edit_is_blocked_by_schedules_and_historical_snapshots(self):
        self.client.force_authenticate(self.admin)
        scheduled = Game.objects.create(name="Scheduled Category")
        WeeklyGameSchedule.objects.create(
            game=scheduled,
            weekday=Weekday.MONDAY,
            category="TIMED",
            closing_time=time(10),
            draw_time=time(11),
            display_order=8,
        )
        response = self.client.patch(
            f"/api/games/{scheduled.pk}/",
            {"category": "GHANA_GAME"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", response.data)

        historical = Game.objects.create(name="Historical Category")
        sheet = DailySheet.objects.create(
            agency=Agency.objects.first(),
            transaction_date=date(2026, 8, 24),
            created_by=self.admin,
        )
        snapshot = DailySheetGame.objects.create(
            daily_sheet=sheet,
            game=historical,
            game_name_snapshot=historical.name,
            category_snapshot="TIMED",
        )
        response = self.client.patch(
            f"/api/games/{historical.pk}/",
            {"category": "DOUBLE_CHANCE"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.category_snapshot, "TIMED")
        self.assertEqual(response.data["category"], "DOUBLE_CHANCE")

    def test_deactivation_confirmation_and_lifecycle_audit(self):
        self.client.force_authenticate(self.admin)
        monday_timed = WeeklyGameSchedule.objects.filter(
            weekday=Weekday.MONDAY,
            category="TIMED",
            is_active=True,
        ).order_by("display_order").first()
        self.assertIsNotNone(monday_timed)
        available_slot = self.client.patch(
            f"/api/weekly-game-schedules/{monday_timed.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(available_slot.status_code, status.HTTP_200_OK, available_slot.data)
        game = Game.objects.create(name="Assigned Game")
        WeeklyGameSchedule.objects.create(
            game=game,
            weekday=Weekday.MONDAY,
            category="TIMED",
            closing_time=time(10),
            draw_time=time(11),
            display_order=8,
        )
        missing_confirmation = self.client.patch(
            f"/api/games/{game.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(missing_confirmation.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(missing_confirmation.data["confirmation_required"], True)
        self.assertEqual(missing_confirmation.data["affected_weekdays"], ["Monday"])
        game.refresh_from_db()
        self.assertTrue(game.is_active)

        deactivated = self.client.patch(
            f"/api/games/{game.pk}/",
            {"is_active": False, "confirm_deactivation": True},
            format="json",
        )
        reactivated = self.client.patch(f"/api/games/{game.pk}/", {"is_active": True}, format="json")
        self.assertEqual(deactivated.status_code, status.HTTP_200_OK, deactivated.data)
        self.assertEqual(reactivated.status_code, status.HTTP_200_OK, reactivated.data)
        self.assertEqual(
            set(AuditLog.objects.filter(model_name="Game", object_id=str(game.pk)).values_list("action", flat=True)),
            {AuditAction.GAME_DEACTIVATED, AuditAction.GAME_REACTIVATED},
        )

    def test_game_reactivation_cannot_overflow_full_weekday(self):
        self.client.force_authenticate(self.admin)
        monday_timed = WeeklyGameSchedule.objects.filter(
            weekday=Weekday.MONDAY,
            category="TIMED",
            is_active=True,
        ).order_by("display_order").first()
        self.assertIsNotNone(monday_timed)
        removed = self.client.patch(
            f"/api/weekly-game-schedules/{monday_timed.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(removed.status_code, status.HTTP_200_OK, removed.data)

        game = Game.objects.create(name="Reactivation Capacity Game", category="TIMED")
        assignment = self.client.post(
            "/api/weekly-game-schedules/",
            {
                "game": game.pk,
                "weekday": Weekday.MONDAY,
                "category": "TIMED",
                "is_whole_day": False,
                "closing_time": "12:30",
                "draw_time": "12:45",
                "display_order": monday_timed.display_order,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(assignment.status_code, status.HTTP_201_CREATED, assignment.data)
        deactivated = self.client.patch(
            f"/api/games/{game.pk}/",
            {"is_active": False, "confirm_deactivation": True},
            format="json",
        )
        self.assertEqual(deactivated.status_code, status.HTTP_200_OK, deactivated.data)

        replacement_game = Game.objects.create(name="Replacement Capacity Game", category="TIMED")
        replacement = self.client.post(
            "/api/weekly-game-schedules/",
            {
                "game": replacement_game.pk,
                "weekday": Weekday.MONDAY,
                "category": "TIMED",
                "is_whole_day": False,
                "closing_time": "13:00",
                "draw_time": "13:15",
                "display_order": 8,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(replacement.status_code, status.HTTP_201_CREATED, replacement.data)

        rejected = self.client.patch(
            f"/api/games/{game.pk}/",
            {"is_active": True},
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Monday", rejected.data["is_active"][0])

        replacement_deactivated = self.client.patch(
            f"/api/weekly-game-schedules/{replacement.data['id']}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(replacement_deactivated.status_code, status.HTTP_200_OK, replacement_deactivated.data)
        reactivated = self.client.patch(f"/api/games/{game.pk}/", {"is_active": True}, format="json")
        self.assertEqual(reactivated.status_code, status.HTTP_200_OK, reactivated.data)

    def test_schedule_category_alias_and_unique_active_display_order(self):
        self.client.force_authenticate(self.admin)
        game = Game.objects.create(name="Ghana Alias Game", category="GHANA")
        alias = self.client.post(
            "/api/weekly-game-schedules/",
            {
                "game": game.pk,
                "weekday": Weekday.MONDAY,
                "category": "GHANA_GAME",
                "is_whole_day": True,
                "display_order": 8,
                "is_active": False,
            },
            format="json",
        )
        self.assertEqual(alias.status_code, status.HTTP_201_CREATED, alias.data)
        self.assertEqual(alias.data["category"], "GHANA")

        existing_assignment = WeeklyGameSchedule.objects.get(
            weekday=Weekday.MONDAY,
            display_order=7,
            is_active=True,
        )
        deactivated = self.client.patch(
            f"/api/weekly-game-schedules/{existing_assignment.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(deactivated.status_code, status.HTTP_200_OK, deactivated.data)
        other = Game.objects.create(name="Order Collision")
        duplicate_order = self.client.post(
            "/api/weekly-game-schedules/",
            {
                "game": other.pk,
                "weekday": Weekday.MONDAY,
                "category": "TIMED",
                "is_whole_day": False,
                "closing_time": "08:00",
                "draw_time": "08:30",
                "display_order": 1,
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(duplicate_order.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("display_order", duplicate_order.data)

    def test_case_insensitive_game_name_database_constraint(self):
        Game.objects.create(name="Case Check")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Game.objects.create(name="case check")


class ScheduleReadinessAndDailySheetSafetyTests(APITestCase):
    def setUp(self):
        call_command("seed_initial_data", stdout=StringIO())
        self.admin = User.objects.create_superuser("schedule-admin@example.com", "pass-12345", full_name="Admin")
        self.accountant = User.objects.create_user("schedule-accountant@example.com", "pass-12345", full_name="Accountant")
        self.agency = Agency.objects.create(name="Schedule Agency", code="schedule-agency")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True)

    def test_wip_is_allowed_but_invalid_effective_schedule_blocks_new_sheets(self):
        monday = WeeklyGameSchedule.objects.get(
            weekday=Weekday.MONDAY, game__name="Peoples", is_active=True,
        )
        self.client.force_authenticate(self.admin)
        deactivated = self.client.patch(
            f"/api/weekly-game-schedules/{monday.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(deactivated.status_code, status.HTTP_200_OK, deactivated.data)

        summary = self.client.get("/api/weekly-game-schedules/validation/")
        monday_summary = next(row for row in summary.data["weekdays"] if row["weekday"] == Weekday.MONDAY)
        self.assertFalse(summary.data["ready"])
        self.assertFalse(monday_summary["ready"])
        self.assertEqual(monday_summary["active_game_count"], 6)

        self.client.force_authenticate(self.accountant)
        effective = self.client.get("/api/games/for-date/?date=2026-08-24")
        manual = self.client.post(
            "/api/daily-sheets/",
            {"agency": self.agency.pk, "transaction_date": "2026-08-31"},
            format="json",
        )
        self.assertEqual(effective.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("schedule", effective.data)
        self.assertEqual(manual.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("schedule", manual.data)
        self.assertFalse(DailySheet.objects.filter(agency=self.agency).exists())

    def test_schedule_incomplete_at_import_preview_and_confirm_is_rejected_but_existing_sheet_uses_snapshots(self):
        from core.tests.test_daily_sheet_imports import workbook_upload
        from core.models import DailySheetImportBatch

        self.client.force_authenticate(self.accountant)
        existing_sheet = DailySheet.objects.create(
            agency=self.agency,
            transaction_date=date(2026, 8, 24),
            created_by=self.accountant,
        )
        existing_sheet.copy_weekday_games()
        valid_preview = self.client.post(
            "/api/daily-sheet-imports/preview/",
            {
                "agency": self.agency.pk,
                "transaction_date": "2026-08-31",
                "file": workbook_upload(
                    headers=APPROVED_WEEKLY_GAME_NAMES[Weekday.MONDAY],
                    raw_date=date(2026, 8, 31),
                ),
            },
            format="multipart",
        )
        self.assertEqual(valid_preview.status_code, status.HTTP_201_CREATED, valid_preview.data)

        self.client.force_authenticate(self.admin)
        monday = WeeklyGameSchedule.objects.get(
            weekday=Weekday.MONDAY, game__name="Peoples", is_active=True,
        )
        self.client.patch(
            f"/api/weekly-game-schedules/{monday.pk}/",
            {"is_active": False},
            format="json",
        )
        self.client.force_authenticate(self.accountant)
        confirm = self.client.post(
            f"/api/daily-sheet-imports/{valid_preview.data['id']}/confirm/",
            {},
            format="json",
        )
        self.assertEqual(confirm.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("schedule", confirm.data)
        self.assertFalse(DailySheet.objects.filter(agency=self.agency, transaction_date=date(2026, 8, 31)).exists())

        incomplete_preview = self.client.post(
            "/api/daily-sheet-imports/preview/",
            {
                "agency": self.agency.pk,
                "transaction_date": "2026-09-07",
                "file": workbook_upload(
                    headers=APPROVED_WEEKLY_GAME_NAMES[Weekday.MONDAY],
                    raw_date=date(2026, 9, 7),
                ),
            },
            format="multipart",
        )
        self.assertEqual(incomplete_preview.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            DailySheetImportBatch.objects.get(pk=incomplete_preview.data["id"]).status,
            "FAILED",
        )

        historical_preview = self.client.post(
            "/api/daily-sheet-imports/preview/",
            {
                "agency": self.agency.pk,
                "transaction_date": "2026-08-24",
                "file": workbook_upload(
                    headers=APPROVED_WEEKLY_GAME_NAMES[Weekday.MONDAY],
                    raw_date=date(2026, 8, 24),
                ),
            },
            format="multipart",
        )
        self.assertEqual(historical_preview.status_code, status.HTTP_201_CREATED, historical_preview.data)
        historical_confirm = self.client.post(
            f"/api/daily-sheet-imports/{historical_preview.data['id']}/confirm/",
            {},
            format="json",
        )
        self.assertEqual(historical_confirm.status_code, status.HTTP_200_OK, historical_confirm.data)
        self.assertEqual(historical_confirm.data["daily_sheet"], existing_sheet.pk)
