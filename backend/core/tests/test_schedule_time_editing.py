from copy import deepcopy
from datetime import date, time
from unittest.mock import patch

from django.test import TestCase

from core.models import AuditLog, DailySheet, Game, PaymentObligation, User, WeeklyGameSchedule
from core.tests.test_payment_games import GameFixture


class ScheduleTimeEditingTests(GameFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.schedule = WeeklyGameSchedule.objects.get(game_id=self.payload['game'], weekday=1, is_active=True)
        self.path = f'/api/weekly-game-schedules/{self.schedule.pk}/'

    def test_edit_preserves_sheet_obligation_payment_and_receipt_history(self):
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        obligation = PaymentObligation.objects.get(pk=created.data['id'])
        original = deepcopy(obligation.game_snapshot)
        payment = self.pay(obligation.pk, 'schedule-history')
        self.assertEqual(payment.status_code, 201, payment.data)
        sheet = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 11, 9), created_by=self.admin)
        sheet.copy_weekday_games()
        snapshot = sheet.sheet_games.get(game_id=self.schedule.game_id)
        previous_times = (snapshot.closing_time_snapshot, snapshot.draw_time_snapshot)

        edited = self.client.patch(self.path, {'closing_time': '13:00', 'draw_time': '13:15'}, format='json')
        self.assertEqual(edited.status_code, 200, edited.data)
        audit = AuditLog.objects.get(action='SCHEDULE_UPDATED', object_id=str(self.schedule.pk))
        self.assertEqual(audit.user_id, self.admin.pk)
        self.assertIsNotNone(audit.created_at)
        self.assertEqual(audit.old_values['closing_time'], '12:30:00')
        self.assertEqual(audit.new_values['closing_time'], '13:00:00')
        self.assertEqual(audit.new_values['timezone'], 'Africa/Accra')
        obligation.refresh_from_db()
        snapshot.refresh_from_db()
        self.assertEqual(obligation.game_snapshot, original)
        self.assertEqual((snapshot.closing_time_snapshot, snapshot.draw_time_snapshot), previous_times)
        later_payment = self.pay(obligation.pk, 'after-schedule-edit')
        self.assertEqual(later_payment.status_code, 201, later_payment.data)
        self.assertEqual(later_payment.data['game_snapshot'], original)
        receipt = self.client.get(f"/api/payer-payments/{payment.data['id']}/receipt/")
        self.assertEqual(receipt.status_code, 200)
        self.assertIn(b'12:30:00', receipt.content)
        future = self.create(business_date='2026-11-16', obligation_date='2026-11-16')
        self.assertEqual(future.status_code, 201, future.data)
        self.assertEqual(PaymentObligation.objects.get(pk=future.data['id']).game_snapshot['closing_time'], '13:00:00')
        new_sheet = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 11, 16), created_by=self.admin)
        new_sheet.copy_weekday_games()
        self.assertEqual(new_sheet.sheet_games.get(game_id=self.schedule.game_id).closing_time_snapshot, time(13))

    def test_accountant_cannot_change_times_even_with_staff_flags(self):
        user = User.objects.create_user(email='schedule-staff@example.com', password='Testpass123!', is_staff=True, is_superuser=True)
        self.client.force_authenticate(user)
        for method in ('patch', 'put', 'delete'):
            response = getattr(self.client, method)(self.path, {'closing_time': '13:00', 'draw_time': '13:15'}, format='json')
            self.assertEqual(response.status_code, 403)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.closing_time, time(12, 30))

    def test_invalid_time_edits_leave_schedule_and_audit_unchanged(self):
        for changes in ({'closing_time': None}, {'draw_time': '12:30'}, {'draw_time': '11:00'}, {'closing_time': '25:00'}, {'closing_time': 'bad'}):
            with self.subTest(changes=changes):
                response = self.client.patch(self.path, changes, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.closing_time, time(12, 30))
        self.assertFalse(AuditLog.objects.filter(action='SCHEDULE_UPDATED', object_id=str(self.schedule.pk)).exists())

    def test_audit_failure_rolls_back_time_edit(self):
        with patch('core.views.log_audit', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.patch(self.path, {'closing_time': '13:00', 'draw_time': '13:15'}, format='json')
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.closing_time, time(12, 30))

    def test_ghana_game_can_be_created_without_inventing_schedule_times(self):
        response = self.client.post('/api/games/', {'name': 'Ghana Game', 'category': 'TIMED', 'is_active': True}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        game = Game.objects.get(pk=response.data['id'])
        self.assertFalse(game.weekly_schedules.exists())
        self.assertEqual(game.category, 'TIMED')
        self.assertTrue(AuditLog.objects.filter(action='GAME_CREATED', object_id=str(game.pk)).exists())
        missing_times = self.client.patch(self.path, {'game': game.pk, 'closing_time': None, 'draw_time': None}, format='json')
        self.assertEqual(missing_times.status_code, 400)
        assigned = self.client.patch(self.path, {'game': game.pk, 'closing_time': '14:00', 'draw_time': '14:15'}, format='json')
        self.assertEqual(assigned.status_code, 200, assigned.data)
        created = self.create(game=game.pk)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(PaymentObligation.objects.get(pk=created.data['id']).game_snapshot['name'], 'Ghana Game')
