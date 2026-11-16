import importlib
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from core.game_schedule import apply_approved_weekly_game_schedule
from core.holiday_overrides import effective_schedule_for_date
from core.importers import schedule_snapshot_for_date
from core.models import PaymentPayer, PaymentObligation, COMMISSION_RATE, Game, WeeklyGameSchedule, DailySheetGame
from core.tests.test_phase_2 import Phase2Mixin
from core.views import DailySheetImportBatchViewSet


def migrate_schedule():
    constraint = next(
        constraint
        for constraint in WeeklyGameSchedule._meta.constraints
        if constraint.name == "unique_active_weekday_display_order"
    )
    migration_schema = SimpleNamespace(connection=connection)
    with connection.schema_editor() as schema_editor:
        schema_editor.remove_constraint(WeeklyGameSchedule, constraint)
    try:
        legacy_apps = MigrationExecutor(connection).loader.project_state(
            [("core", "0022_game_categories")]
        ).apps
        importlib.import_module("core.migrations.0023_confirmed_weekly_schedule").update_schedule(
            legacy_apps, migration_schema)
        importlib.import_module(
            "core.migrations.0027_game_catalogue_and_schedule_constraints"
        ).repair_active_display_order(apps, migration_schema)
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.add_constraint(WeeklyGameSchedule, constraint)


class CategoryScheduleTests(Phase2Mixin, TransactionTestCase):
    def setUp(self):
        self.build_base()

    def test_mapping_counts_categories_snapshots_and_duplicate(self):
        apply_approved_weekly_game_schedule()
        for day, name in enumerate(["MSP", "Lucky Ghana", "Midweek", "Fortune", "Bonanza", "National", "Aseda"], 1):
            with self.subTest(day=day):
                rows, _ = effective_schedule_for_date(date(2026, 8, 24) + timedelta(days=day - 1))
                self.assertEqual(len(rows), 6 if day == 7 else 7)
                self.assertEqual([r.game.name for r in rows if r.category == "GHANA"], [name])
                self.assertEqual([r.game.name for r in rows if r.category == "DOUBLE_CHANCE"], ["Double Chance"])
                for row in rows:
                    self.assertEqual(row.is_whole_day, row.category != "TIMED")
                view = DailySheetImportBatchViewSet()
                dt = date(2026, 8, 24) + timedelta(days=day - 1)
                with transaction.atomic():
                    self.assertEqual(view._current_schedule_snapshot(dt), schedule_snapshot_for_date(dt, None))
        sheet = self.create_sheet()
        self.assertEqual(set(sheet.sheet_games.filter(is_whole_day_snapshot=True).values_list("category_snapshot", flat=True)), {"GHANA", "DOUBLE_CHANCE"})
        dc = WeeklyGameSchedule.objects.get(weekday=1, category="DOUBLE_CHANCE")
        with self.assertRaises(ValidationError):
            WeeklyGameSchedule.objects.create(game=dc.game, weekday=1, category="DOUBLE_CHANCE", is_whole_day=True)

    def test_migration_idempotent_preserves_history_timed_rows_and_five_percent(self):
        apply_approved_weekly_game_schedule()
        legacy = Game.objects.create(name="Monday Special")
        WeeklyGameSchedule.objects.filter(weekday=1, category="GHANA").update(game=legacy)
        sheet = self.create_sheet(commission_rate="0.05")
        # Represent a pre-category snapshot: do not backfill it from current games.
        sheet.sheet_games.update(category_snapshot=None)
        txn = self.create_transaction(sheet, self.tpm_one, "100", "200")
        payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Schedule payer", created_by=self.super_admin)
        obligation = PaymentObligation.objects.create(agency=self.agency, payer=payer, description="Historical", obligation_date=sheet.transaction_date, total_expected=txn.to_pay, created_by=self.super_admin)
        obligation_before = PaymentObligation.objects.values().get(pk=obligation.pk)
        before = list(sheet.sheet_games.values())
        totals = sheet.totals()
        timed = list(
            WeeklyGameSchedule.objects.filter(category="TIMED")
            .order_by("weekday", "display_order", "pk")
            .values("pk", "game_id", "weekday", "category", "is_whole_day", "closing_time", "draw_time", "is_active")
        )
        migrate_schedule()
        schedules = list(WeeklyGameSchedule.objects.values())
        migrate_schedule()
        self.assertEqual(schedules, list(WeeklyGameSchedule.objects.values()))
        self.assertEqual(
            timed,
            list(
                WeeklyGameSchedule.objects.filter(category="TIMED")
                .order_by("weekday", "display_order", "pk")
                .values("pk", "game_id", "weekday", "category", "is_whole_day", "closing_time", "draw_time", "is_active")
            ),
        )
        sheet.copy_weekday_games()
        self.assertEqual(before, list(sheet.sheet_games.values()))
        self.assertEqual(sheet.totals(), totals)
        self.assertEqual(PaymentObligation.objects.values().get(pk=obligation.pk), obligation_before)
        self.assertEqual(obligation.total_expected, Decimal("285"))
        self.assertEqual(COMMISSION_RATE, Decimal("0.02"))
        self.assertEqual(txn.net_sales, Decimal("300"))
        self.assertEqual(txn.commission, Decimal("15"))
        self.assertEqual(txn.to_pay, Decimal("285"))
        legacy.refresh_from_db()
        self.assertEqual(legacy.name, "Monday Special")
        self.assertTrue(DailySheetGame.objects.filter(game=legacy, game_name_snapshot="Monday Special", category_snapshot=None).exists())
        self.assertEqual(WeeklyGameSchedule.objects.filter(category="GHANA", is_active=True).count(), 7)
        self.assertEqual(WeeklyGameSchedule.objects.filter(category="DOUBLE_CHANCE", is_active=True).count(), 7)

    def test_full_legacy_schedule_migrates_without_changing_timed_games(self):
        apply_approved_weekly_game_schedule()
        WeeklyGameSchedule.objects.filter(category="DOUBLE_CHANCE").delete()
        for day, legacy_name in [(1, "Monday Special"), (2, "Lucky G")]:
            legacy = Game.objects.create(name=legacy_name)
            WeeklyGameSchedule.objects.filter(weekday=day, category="GHANA").update(game=legacy)
        WeeklyGameSchedule.objects.update(category="TIMED")
        timed = list(
            WeeklyGameSchedule.objects.filter(is_whole_day=False)
            .order_by("weekday", "display_order", "pk")
            .values("pk", "game_id", "weekday", "category", "is_whole_day", "closing_time", "draw_time", "is_active")
        )
        migrate_schedule()
        self.assertEqual(
            timed,
            list(
                WeeklyGameSchedule.objects.filter(is_whole_day=False)
                .order_by("weekday", "display_order", "pk")
                .values("pk", "game_id", "weekday", "category", "is_whole_day", "closing_time", "draw_time", "is_active")
            ),
        )
        for day, name in enumerate(["MSP", "Lucky Ghana", "Midweek", "Fortune", "Bonanza", "National", "Aseda"], 1):
            active = WeeklyGameSchedule.objects.filter(weekday=day, is_active=True)
            self.assertEqual(active.count(), 6 if day == 7 else 7)
            self.assertEqual(active.get(category="GHANA").game.name, name)
            self.assertEqual(active.get(category="DOUBLE_CHANCE").game.name, "Double Chance")
        before = list(WeeklyGameSchedule.objects.values())
        migrate_schedule()
        self.assertEqual(before, list(WeeklyGameSchedule.objects.values()))
