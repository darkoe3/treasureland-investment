import importlib
from datetime import date, time

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


MIGRATE_FROM = ("core", "0019_dailysheet_holiday_name_snapshot_and_more")
MIGRATE_TO = ("core", "0020_correct_wednesday_lucky_schedule")


class WednesdayLuckyDataMigrationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([MIGRATE_FROM])
        self.old_apps = MigrationExecutor(connection).loader.project_state([MIGRATE_FROM]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def create_wednesday_schedule(self, include_lucky=True):
        Game = self.old_apps.get_model("core", "Game")
        WeeklyGameSchedule = self.old_apps.get_model("core", "WeeklyGameSchedule")
        rows = []
        names = ["Mark II", "VAG", "Midweek", "Enugu"]
        if include_lucky:
            names.append("Lucky")
        names.append("Tota")
        for display_order, name in enumerate(names, start=1):
            game = Game.objects.create(name=name)
            whole_day = name == "Midweek" or name == "Lucky"
            rows.append(
                WeeklyGameSchedule.objects.create(
                    game=game,
                    weekday=3,
                    is_whole_day=whole_day,
                    closing_time=None if whole_day else time(12, 30),
                    draw_time=None if whole_day else time(12, 45),
                    display_order=display_order,
                    is_active=True,
                )
            )
        return rows

    def migrate_forward(self):
        MigrationExecutor(connection).migrate([MIGRATE_TO])
        return MigrationExecutor(connection).loader.project_state([MIGRATE_TO]).apps

    def test_existing_lucky_schedule_is_corrected_and_snapshots_are_untouched(self):
        rows = self.create_wednesday_schedule()
        lucky = next(row for row in rows if row.game.name == "Lucky")
        self.assertEqual(lucky.display_order, 5)

        Game = self.old_apps.get_model("core", "Game")
        Agency = self.old_apps.get_model("core", "Agency")
        User = self.old_apps.get_model("core", "User")
        DailySheet = self.old_apps.get_model("core", "DailySheet")
        DailySheetGame = self.old_apps.get_model("core", "DailySheetGame")
        lucky_game = Game.objects.get(name="Lucky")
        agency = Agency.objects.create(name="Migration Test", code="migration-test")
        user = User.objects.create(email="migration@example.com", full_name="Migration Test")
        sheet = DailySheet.objects.create(
            agency=agency,
            transaction_date=date(2026, 9, 23),
            created_by=user,
        )
        snapshot = DailySheetGame.objects.create(
            daily_sheet=sheet,
            game=lucky_game,
            game_name_snapshot="Lucky",
            is_whole_day_snapshot=True,
            closing_time_snapshot=None,
            draw_time_snapshot=None,
            display_order=5,
        )

        current_apps = self.migrate_forward()
        CurrentSchedule = current_apps.get_model("core", "WeeklyGameSchedule")
        CurrentSnapshot = current_apps.get_model("core", "DailySheetGame")
        schedules = list(
            CurrentSchedule.objects.filter(weekday=3, is_active=True)
            .select_related("game")
            .order_by("display_order")
        )
        updated_lucky = next(row for row in schedules if row.game.name == "Lucky")

        self.assertEqual(len(schedules), 6)
        self.assertFalse(updated_lucky.is_whole_day)
        self.assertEqual(updated_lucky.closing_time, time(22, 30))
        self.assertEqual(updated_lucky.draw_time, time(22, 45))
        self.assertTrue(updated_lucky.is_active)
        self.assertEqual(updated_lucky.display_order, 5)
        self.assertEqual([row.game.name for row in schedules if row.is_whole_day], ["Midweek"])

        unchanged_snapshot = CurrentSnapshot.objects.get(pk=snapshot.pk)
        self.assertTrue(unchanged_snapshot.is_whole_day_snapshot)
        self.assertIsNone(unchanged_snapshot.closing_time_snapshot)
        self.assertIsNone(unchanged_snapshot.draw_time_snapshot)
        self.assertEqual(unchanged_snapshot.game_name_snapshot, "Lucky")

        schedule_count = CurrentSchedule.objects.count()
        game_count = current_apps.get_model("core", "Game").objects.count()
        migration = importlib.import_module("core.migrations.0020_correct_wednesday_lucky_schedule")
        with connection.schema_editor() as schema_editor:
            migration.correct_wednesday_lucky_schedule(current_apps, schema_editor)

        self.assertEqual(CurrentSchedule.objects.count(), schedule_count)
        self.assertEqual(current_apps.get_model("core", "Game").objects.count(), game_count)
        updated_lucky.refresh_from_db()
        self.assertEqual(updated_lucky.closing_time, time(22, 30))
        self.assertEqual(updated_lucky.draw_time, time(22, 45))

    def test_missing_lucky_game_or_schedule_is_a_safe_noop(self):
        Game = self.old_apps.get_model("core", "Game")
        WeeklyGameSchedule = self.old_apps.get_model("core", "WeeklyGameSchedule")
        unrelated = Game.objects.create(name="Unrelated")
        WeeklyGameSchedule.objects.create(
            game=unrelated,
            weekday=3,
            is_whole_day=False,
            closing_time=time(12, 30),
            draw_time=time(12, 45),
            display_order=1,
            is_active=True,
        )
        Game.objects.create(name="Lucky")

        current_apps = self.migrate_forward()
        CurrentSchedule = current_apps.get_model("core", "WeeklyGameSchedule")
        unrelated_schedule = CurrentSchedule.objects.get(game__name="Unrelated", weekday=3)

        self.assertFalse(CurrentSchedule.objects.filter(game__name="Lucky", weekday=3).exists())
        self.assertEqual(unrelated_schedule.closing_time, time(12, 30))
        self.assertEqual(unrelated_schedule.draw_time, time(12, 45))
        self.assertEqual(current_apps.get_model("core", "Game").objects.count(), 2)

    def test_missing_lucky_game_record_is_a_safe_noop(self):
        rows = self.create_wednesday_schedule(include_lucky=False)
        initial_count = len(rows)

        current_apps = self.migrate_forward()
        CurrentSchedule = current_apps.get_model("core", "WeeklyGameSchedule")

        self.assertFalse(CurrentSchedule.objects.filter(weekday=3, game__name="Lucky").exists())
        self.assertEqual(CurrentSchedule.objects.count(), initial_count)
        self.assertFalse(current_apps.get_model("core", "Game").objects.filter(name="Lucky").exists())