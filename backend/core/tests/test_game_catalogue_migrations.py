import importlib
from datetime import date, time
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


MIGRATE_FROM = ("core", "0025_payment_game_snapshots")
MIGRATE_TO = ("core", "0028_game_category")
FRESH_START = ("core", "0001_initial")


class GameCatalogueMigrationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        self.latest_targets = executor.loader.graph.leaf_nodes()
        self.addCleanup(self.restore_latest_schema)
        executor.migrate(self.latest_targets)
        executor.migrate([MIGRATE_FROM])
        call_command("flush", database=connection.alias, interactive=False, verbosity=0)
        self.old_apps = MigrationExecutor(connection).loader.project_state([MIGRATE_FROM]).apps

    def restore_latest_schema(self):
        MigrationExecutor(connection).migrate(self.latest_targets)

    def migrate_forward(self):
        MigrationExecutor(connection).migrate([MIGRATE_TO])
        return MigrationExecutor(connection).loader.project_state([MIGRATE_TO]).apps

    def create_super_admin(self, apps, email="migration-admin@example.com"):
        User = apps.get_model("core", "User")
        return User.objects.create(
            email=email,
            full_name="Migration Super Admin",
            role="SUPER_ADMIN",
            is_staff=True,
            is_superuser=True,
            is_active=True,
            password="!migration-test-password",
        )

    def test_empty_production_state_preserves_only_the_super_admin(self):
        admin = self.create_super_admin(self.old_apps)
        users_before = list(self.old_apps.get_model("core", "User").objects.order_by("pk").values())

        apps = self.migrate_forward()

        User = apps.get_model("core", "User")
        self.assertEqual(list(User.objects.order_by("pk").values()), users_before)
        self.assertEqual(User.objects.count(), 1)
        for model_name in (
            "Agency",
            "Game",
            "WeeklyGameSchedule",
            "HolidayGameOverride",
            "DailySheet",
            "DailySheetGame",
            "PaymentPayer",
            "PaymentObligation",
            "PayerPayment",
            "AuditLog",
            "OrganisationSettings",
        ):
            with self.subTest(model=model_name):
                self.assertEqual(apps.get_model("core", model_name).objects.count(), 0)
        self.assertEqual(admin.email, "migration-admin@example.com")

    def test_duplicate_orders_are_corrected_and_historical_snapshots_are_preserved(self):
        old = self.old_apps
        User = old.get_model("core", "User")
        Agency = old.get_model("core", "Agency")
        Game = old.get_model("core", "Game")
        Schedule = old.get_model("core", "WeeklyGameSchedule")
        Payer = old.get_model("core", "PaymentPayer")
        Obligation = old.get_model("core", "PaymentObligation")
        Payment = old.get_model("core", "PayerPayment")
        DailySheet = old.get_model("core", "DailySheet")
        DailySheetGame = old.get_model("core", "DailySheetGame")

        admin = self.create_super_admin(old)
        agency = Agency.objects.create(name="Migration Agency", code="migration-agency")
        games = {
            "Timed A": Game.objects.create(name="Timed A", is_active=True),
            "Timed B": Game.objects.create(name="Timed B", is_active=True),
            "Ghana": Game.objects.create(name="Ghana", is_active=True),
            "Double Chance": Game.objects.create(name="Double Chance", is_active=True),
            "Inactive": Game.objects.create(name="Inactive", is_active=False),
        }
        schedule_rows = [
            Schedule.objects.create(
                game=games["Timed A"], weekday=1, category="TIMED", is_whole_day=False,
                closing_time=time(10, 0), draw_time=time(10, 15), display_order=5, is_active=True,
            ),
            Schedule.objects.create(
                game=games["Timed B"], weekday=1, category="TIMED", is_whole_day=False,
                closing_time=time(11, 0), draw_time=time(11, 15), display_order=5, is_active=True,
            ),
            Schedule.objects.create(
                game=games["Ghana"], weekday=1, category="GHANA", is_whole_day=True,
                closing_time=None, draw_time=None, display_order=9, is_active=True,
            ),
            Schedule.objects.create(
                game=games["Double Chance"], weekday=1, category="DOUBLE_CHANCE", is_whole_day=True,
                closing_time=None, draw_time=None, display_order=9, is_active=True,
            ),
            Schedule.objects.create(
                game=games["Inactive"], weekday=1, category="TIMED", is_whole_day=False,
                closing_time=time(12, 0), draw_time=time(12, 15), display_order=5, is_active=False,
            ),
        ]
        inactive_schedule_id = schedule_rows[-1].pk
        intended_ids = [row.pk for row in schedule_rows[:4]]

        payer = Payer.objects.create(agency=agency, payer_name="Snapshot Payer", created_by=admin)
        obligation = Obligation.objects.create(
            agency=agency,
            payer=payer,
            obligation_number="MIG-OBL-1",
            description="Historical obligation",
            obligation_date=date(2026, 11, 1),
            total_expected=Decimal("100.00"),
            created_by=admin,
        )
        payment = Payment.objects.create(
            obligation=obligation,
            receipt_number="MIG-REC-1",
            agency_snapshot=agency.name,
            payer_name_snapshot=payer.payer_name,
            obligation_number_snapshot=obligation.obligation_number,
            obligation_description_snapshot=obligation.description,
            obligation_date_snapshot=obligation.obligation_date,
            expected_amount_snapshot=Decimal("100.00"),
            amount_previously_paid=Decimal("0.00"),
            amount_received=Decimal("25.00"),
            cumulative_amount_paid=Decimal("25.00"),
            balance_after_payment=Decimal("75.00"),
            payment_method="CASH",
            recorded_by=admin,
            idempotency_key="migration-payment-1",
        )
        sheet = DailySheet.objects.create(
            agency=agency,
            transaction_date=date(2026, 11, 2),
            status="APPROVED",
            commission_rate_snapshot=Decimal("0.0500"),
            created_by=admin,
        )
        sheet_game = DailySheetGame.objects.create(
            daily_sheet=sheet,
            game=games["Timed A"],
            game_name_snapshot="Historical Timed A",
            category_snapshot="TIMED",
            closing_time_snapshot=time(10, 0),
            draw_time_snapshot=time(10, 15),
            display_order=5,
        )

        user_snapshot = list(User.objects.order_by("pk").values())
        sheet_snapshot = list(DailySheet.objects.order_by("pk").values())
        sheet_game_snapshot = list(DailySheetGame.objects.order_by("pk").values())
        payer_snapshot = list(Payer.objects.order_by("pk").values())
        obligation_snapshot = list(Obligation.objects.order_by("pk").values())
        payment_snapshot = list(Payment.objects.order_by("pk").values())
        original_game_ids = list(Game.objects.order_by("pk").values_list("pk", flat=True))
        original_assignments = {
            row.pk: (row.game_id, row.weekday, row.category, row.is_active)
            for row in Schedule.objects.order_by("pk")
        }

        apps = self.migrate_forward()
        CurrentGame = apps.get_model("core", "Game")
        CurrentSchedule = apps.get_model("core", "WeeklyGameSchedule")
        self.assertEqual(
            list(CurrentGame.objects.order_by("pk").values_list("pk", flat=True)),
            original_game_ids,
        )
        ordered_ids = list(
            CurrentSchedule.objects.filter(weekday=1, is_active=True)
            .order_by("display_order", "pk")
            .values_list("pk", flat=True)
        )
        self.assertEqual(ordered_ids, intended_ids)
        self.assertEqual(
            list(
                CurrentSchedule.objects.filter(weekday=1, is_active=True)
                .order_by("display_order")
                .values_list("display_order", flat=True)
            ),
            [1, 2, 3, 4],
        )
        inactive_schedule = CurrentSchedule.objects.get(pk=inactive_schedule_id)
        self.assertEqual(inactive_schedule.display_order, 5)
        self.assertEqual(
            {
                row.pk: (row.game_id, row.weekday, row.category, row.is_active)
                for row in CurrentSchedule.objects.order_by("pk")
            },
            original_assignments,
        )
        for name, category in (
            ("Timed A", "TIMED"),
            ("Timed B", "TIMED"),
            ("Ghana", "GHANA"),
            ("Double Chance", "DOUBLE_CHANCE"),
            ("Inactive", "TIMED"),
        ):
            with self.subTest(game=name):
                self.assertEqual(CurrentGame.objects.get(name=name).category, category)

        for model_name, before in (
            ("User", user_snapshot),
            ("DailySheet", sheet_snapshot),
            ("DailySheetGame", sheet_game_snapshot),
            ("PaymentPayer", payer_snapshot),
            ("PaymentObligation", obligation_snapshot),
            ("PayerPayment", payment_snapshot),
        ):
            with self.subTest(model=model_name):
                self.assertEqual(
                    list(apps.get_model("core", model_name).objects.order_by("pk").values()),
                    before,
                )
        self.assertEqual(admin.pk, user_snapshot[0]["id"])
        self.assertEqual(sheet_game.game_name_snapshot, "Historical Timed A")
        self.assertEqual(payment.receipt_number, "MIG-REC-1")

        extra_game = CurrentGame.objects.create(name="Constraint Probe")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CurrentSchedule.objects.create(
                    game=extra_game,
                    weekday=1,
                    category="TIMED",
                    is_whole_day=False,
                    closing_time=time(13, 0),
                    draw_time=time(13, 15),
                    display_order=1,
                    is_active=True,
                )

        before_repeat = list(
            CurrentSchedule.objects.order_by("pk").values_list("pk", "display_order")
        )
        schedule_migration = importlib.import_module(
            "core.migrations.0027_game_catalogue_and_schedule_constraints"
        )
        category_migration = importlib.import_module("core.migrations.0028_game_category")
        with connection.schema_editor() as schema_editor:
            schedule_migration.repair_active_display_order(apps, schema_editor)
            category_migration.backfill_game_categories(apps, schema_editor)
            schedule_migration.repair_active_display_order(apps, schema_editor)
        MigrationExecutor(connection).migrate([MIGRATE_TO])
        self.assertEqual(
            list(CurrentSchedule.objects.order_by("pk").values_list("pk", "display_order")),
            before_repeat,
        )

    def test_fresh_migration_path_adds_no_business_data_after_0025(self):
        executor = MigrationExecutor(connection)
        executor.migrate([FRESH_START])
        call_command("flush", database=connection.alias, interactive=False, verbosity=0)
        fresh_apps = MigrationExecutor(connection).loader.project_state([FRESH_START]).apps
        self.create_super_admin(fresh_apps, email="fresh-admin@example.com")

        MigrationExecutor(connection).migrate([MIGRATE_FROM])
        apps_at_0025 = MigrationExecutor(connection).loader.project_state([MIGRATE_FROM]).apps
        baseline_counts = {
            model_name: apps_at_0025.get_model("core", model_name).objects.count()
            for model_name in (
                "User",
                "Agency",
                "Game",
                "WeeklyGameSchedule",
                "HolidayGameOverride",
                "DailySheet",
                "DailySheetGame",
                "PaymentPayer",
                "PaymentObligation",
                "PayerPayment",
                "AuditLog",
            )
        }
        baseline_users = list(
            apps_at_0025.get_model("core", "User").objects.order_by("pk").values()
        )

        apps = self.migrate_forward()

        for model_name, count in baseline_counts.items():
            with self.subTest(model=model_name):
                self.assertEqual(apps.get_model("core", model_name).objects.count(), count)
        self.assertEqual(
            list(apps.get_model("core", "User").objects.order_by("pk").values()),
            baseline_users,
        )
        self.assertEqual(apps.get_model("core", "User").objects.get().email, "fresh-admin@example.com")
        self.assertEqual(apps.get_model("core", "OrganisationSettings").objects.count(), 0)
