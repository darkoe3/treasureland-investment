from concurrent.futures import ThreadPoolExecutor
from datetime import time
from io import StringIO
import threading
import unittest

from django.core.management import call_command
from django.core.management.color import no_style
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core.models import AuditAction, AuditLog, Game, User, Weekday, WeeklyGameSchedule


@unittest.skipUnless(connection.vendor == "postgresql", "Schedule concurrency tests require PostgreSQL.")
class ScheduleCapacityPostgreSQLConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.reset_game_schedule_sequences()
        call_command("seed_initial_data", stdout=StringIO())
        self.reset_game_schedule_sequences()
        self.admin = User.objects.create_superuser(
            email="pg-schedule-admin@example.com",
            password="SchedulePass123!",
            full_name="PG Schedule Admin",
        )

    @staticmethod
    def reset_game_schedule_sequences():
        statements = connection.ops.sequence_reset_sql(
            no_style(),
            [Game, WeeklyGameSchedule],
        )
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def timed_schedule_payload(self, game, display_order, *, active=True):
        return {
            "game": game.pk,
            "weekday": Weekday.MONDAY,
            "category": "TIMED",
            "is_whole_day": False,
            "closing_time": "12:30",
            "draw_time": "12:45",
            "display_order": display_order,
            "is_active": active,
        }

    def concurrent_request(self, barrier, method, path, payload):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(User.objects.get(pk=self.admin.pk))
            barrier.wait(timeout=15)
            response = getattr(client, method)(path, payload, format="json")
            return response.status_code, response.data
        finally:
            connections["default"].close()

    def assert_one_validation_failure(self, results, success_status):
        statuses = sorted(result[0] for result in results)
        self.assertEqual(statuses, sorted([400, success_status]), results)
        failure = next(data for status_code, data in results if status_code == 400)
        self.assertTrue(failure, "The losing request must receive a validation response.")
        self.assertNotIn(500, statuses)

    def test_simultaneous_schedule_creates_compete_for_last_weekday_slot(self):
        released = WeeklyGameSchedule.objects.get(
            weekday=Weekday.MONDAY,
            is_active=True,
            display_order=6,
        )
        released.is_active = False
        released.save(update_fields=["is_active"])

        games = [
            Game.objects.create(name=f"Concurrent Monday Game {index}", category="TIMED")
            for index in range(2)
        ]
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda item: self.concurrent_request(
                    barrier,
                    "post",
                    "/api/weekly-game-schedules/",
                    self.timed_schedule_payload(item[1], 6 + item[0] * 2),
                ),
                enumerate(games),
            ))

        self.assert_one_validation_failure(results, 201)
        failure = next(data for status_code, data in results if status_code == 400)
        self.assertIn("weekday", failure)
        self.assertIn("active", str(failure).lower())
        active_count = WeeklyGameSchedule.objects.filter(
            weekday=Weekday.MONDAY,
            is_active=True,
            game__is_active=True,
        ).count()
        self.assertEqual(active_count, 7)

    def test_schedule_and_game_reactivation_compete_for_last_weekday_slot(self):
        released = WeeklyGameSchedule.objects.get(
            weekday=Weekday.MONDAY,
            is_active=True,
            display_order=6,
        )
        released.is_active = False
        released.save(update_fields=["is_active"])

        game_to_reactivate = Game.objects.create(name="Concurrent Game Reactivation", category="TIMED")
        scheduled_game = WeeklyGameSchedule.objects.create(
            game=game_to_reactivate,
            weekday=Weekday.MONDAY,
            category="TIMED",
            is_whole_day=False,
            closing_time=time(12, 30),
            draw_time=time(12, 45),
            display_order=6,
            is_active=True,
        )
        game_to_reactivate.is_active = False
        game_to_reactivate.save(update_fields=["is_active"])

        game_for_schedule = Game.objects.create(name="Concurrent Schedule Reactivation", category="TIMED")
        schedule_to_reactivate = WeeklyGameSchedule.objects.create(
            game=game_for_schedule,
            weekday=Weekday.MONDAY,
            category="TIMED",
            is_whole_day=False,
            closing_time=time(13, 30),
            draw_time=time(13, 45),
            display_order=8,
            is_active=False,
        )
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            schedule_result = pool.submit(
                self.concurrent_request,
                barrier,
                "patch",
                f"/api/weekly-game-schedules/{schedule_to_reactivate.pk}/",
                {"is_active": True},
            )
            game_result = pool.submit(
                self.concurrent_request,
                barrier,
                "patch",
                f"/api/games/{game_to_reactivate.pk}/",
                {"is_active": True},
            )
            results = [schedule_result.result(), game_result.result()]

        self.assert_one_validation_failure(results, 200)
        failure = next(data for status_code, data in results if status_code == 400)
        self.assertTrue({"weekday", "is_active"} & set(failure), failure)
        self.assertIn("active", str(failure).lower())
        self.assertEqual(
            WeeklyGameSchedule.objects.filter(
                weekday=Weekday.MONDAY,
                is_active=True,
                game__is_active=True,
            ).count(),
            7,
        )
        schedule_to_reactivate.refresh_from_db()
        game_to_reactivate.refresh_from_db()
        if schedule_to_reactivate.is_active:
            self.assertTrue(AuditLog.objects.filter(
                action=AuditAction.SCHEDULE_ACTIVATED,
                object_id=str(schedule_to_reactivate.pk),
            ).exists())
        if game_to_reactivate.is_active:
            self.assertTrue(AuditLog.objects.filter(
                action=AuditAction.GAME_REACTIVATED,
                object_id=str(game_to_reactivate.pk),
            ).exists())
        self.assertTrue(scheduled_game.is_active)

    def test_competing_connected_game_edits_serialize_validation_save_and_audit(self):
        released = WeeklyGameSchedule.objects.get(
            weekday=Weekday.MONDAY,
            is_active=True,
            display_order=6,
        )
        released.is_active = False
        released.save(update_fields=["is_active"])
        games = [
            Game.objects.create(name=f"Connected concurrent game {index}", category="TIMED", is_active=False)
            for index in range(2)
        ]
        schedules = [
            WeeklyGameSchedule.objects.create(
                game=game,
                weekday=Weekday.MONDAY,
                category="TIMED",
                is_whole_day=False,
                closing_time=time(12, 30),
                draw_time=time(12, 45),
                display_order=8 + index,
                is_active=False,
            )
            for index, game in enumerate(games)
        ]
        payloads = [
            {
                "name": game.name,
                "category": "TIMED",
                "is_active": True,
                "assignments": [{
                    "id": schedule.pk,
                    "weekday": Weekday.MONDAY,
                    "display_order": released.display_order,
                    "is_active": True,
                    "closing_time": "12:30",
                    "draw_time": "12:45",
                }],
            }
            for game, schedule in zip(games, schedules)
        ]
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda item: self.concurrent_request(
                    barrier,
                    "post",
                    f"/api/games/{item[1].pk}/edit-schedule/",
                    payloads[item[0]],
                ),
                enumerate(games),
            ))

        self.assertEqual(sorted(result[0] for result in results), [200, 400], results)
        failure = next(data for status_code, data in results if status_code == 400)
        self.assertIn("weekday_conflicts", failure)
        self.assertEqual(
            WeeklyGameSchedule.objects.filter(
                weekday=Weekday.MONDAY,
                is_active=True,
                game__is_active=True,
            ).count(),
            7,
        )
        active_competitors = []
        for game in games:
            game.refresh_from_db()
            if game.weekly_schedules.filter(weekday=Weekday.MONDAY, is_active=True).exists() and game.is_active:
                active_competitors.append(game)
        self.assertEqual(len(active_competitors), 1)
        self.assertEqual(
            AuditLog.objects.filter(action=AuditAction.GAME_REACTIVATED, object_id__in=[str(game.pk) for game in games]).count(),
            1,
        )
