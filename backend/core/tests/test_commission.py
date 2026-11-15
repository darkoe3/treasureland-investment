from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from core.models import DailySheet, DailySheetGame, Game, TPMDailyTransaction, TransactionGameSale
from core.game_schedule import apply_approved_weekly_game_schedule
from core.reports import build_report, build_workbook
from core.tests.test_phase_2 import Phase2Mixin


class CommissionTests(Phase2Mixin, APITestCase):
    def setUp(self):
        self.build_base()

    def test_manual_creation_policy_and_readonly_snapshot(self):
        apply_approved_weekly_game_schedule()
        self.client.force_authenticate(self.accountant)
        policy = self.client.get('/api/daily-sheets/commission-policy/')
        self.assertEqual(Decimal(policy.data['commission_rate']), Decimal('.02'))
        response = self.client.post('/api/daily-sheets/', {
            'agency': self.agency.pk, 'transaction_date': '2026-08-24',
            'commission_rate_snapshot': '.05',
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['commission_rate_snapshot']), Decimal('.02'))

    def test_examples_rounding_and_every_category(self):
        sheet = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 8, 24), created_by=self.accountant)
        for net, commission, payable in [('10000', '200', '9800'), ('50000', '1000', '49000'), ('.25', '.01', '.24'), ('.24', '0', '.24')]:
            self.assertEqual(sheet.commission_for(net), Decimal(commission))
            self.assertEqual(sheet.to_pay_for(net), Decimal(payable))
        txn = TPMDailyTransaction.objects.create(daily_sheet=sheet, tpm_code=self.tpm_one, created_by=self.accountant, updated_by=self.accountant)
        for category in ['GHANA', 'DOUBLE_CHANCE', 'TIMED']:
            game = Game.objects.create(name=category)
            snapshot = DailySheetGame.objects.create(daily_sheet=sheet, game=game, game_name_snapshot=category, category_snapshot=category)
            sale = TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=snapshot, amount=Decimal('10000'))
            self.assertEqual(txn.commission, Decimal('200'))
            self.assertEqual(txn.to_pay, Decimal('9800'))
            sale.delete()

    def test_old_draft_edit_and_immutable_rate(self):
        sheet = self.create_sheet(commission_rate='.05')
        self.create_transaction(sheet, self.tpm_one, '.10')
        self.assertEqual(sheet.totals()['total_to_pay'], Decimal('.10'))
        sheet.reconciliation_note = 'Edited draft'
        sheet.save()
        self.client.force_authenticate(self.super_admin)
        response = self.client.patch(f'/api/daily-sheets/{sheet.pk}/', {'commission_rate_snapshot': '.02'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        sheet.refresh_from_db()
        self.assertEqual(sheet.commission_rate_snapshot, Decimal('.05'))
        for state in ['DRAFT', 'SUBMITTED', 'APPROVED', 'RETURNED', 'REOPENED']:
            sheet.status = state
            sheet.save()
            self.assertEqual(sheet.to_pay_for('10000'), Decimal('9500'))
        sheet.commission_rate_snapshot = Decimal('.02')
        with self.assertRaises(ValidationError):
            sheet.save()
        with self.assertRaises(ValidationError):
            DailySheet.objects.filter(pk=sheet.pk).update(commission_rate_snapshot=Decimal('.02'))
        with self.assertRaises(ValidationError):
            DailySheet.objects.bulk_update([sheet], ['commission_rate_snapshot'])

    def test_mixed_reports_and_export(self):
        old = self.create_sheet(commission_rate='.05')
        new = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 8, 25), created_by=self.accountant)
        for game in old.sheet_games.all():
            DailySheetGame.objects.create(
                daily_sheet=new, game=game.game,
                game_name_snapshot=game.game_name_snapshot,
                category_snapshot=game.category_snapshot,
            )
        self.create_transaction(old, self.tpm_one, '10000')
        self.create_transaction(new, self.tpm_one, '50000')
        report = build_report({'agency': str(self.agency.pk), 'period': 'weekly', 'date': '2026-08-24', 'include_drafts': 'true'}, self.super_admin)
        # Report defaults may filter draft sheets; approve using the normal stored state.
        if not report['summary']['daily_sheet_count']:
            DailySheet.objects.filter(pk__in=[old.pk, new.pk]).update(status='APPROVED')
            report = build_report({'agency': str(self.agency.pk), 'period': 'weekly', 'date': '2026-08-24'}, self.super_admin)
        self.assertEqual(report['summary']['total_commission'], Decimal('1500'))
        self.assertEqual(report['summary']['total_to_pay'], Decimal('58500'))
        self.assertEqual(sum(row['to_pay'] for row in report['details']), Decimal('58500'))
        self.assertEqual({row['commission_rate_snapshot'] for row in report['daily_reconciliation']}, {Decimal('.05'), Decimal('.02')})
        values = [cell.value for row in build_workbook(report).active for cell in row]
        self.assertTrue(any(str(value).rstrip('0').startswith('5.') or value == '5%' for value in values))
        self.assertIn('Commission rate', values)


class CommissionMigrationTests(TransactionTestCase):
    def test_backfill_preserves_all_columns_and_repeat_migrate_is_noop(self):
        before = [('core', '0023_confirmed_weekly_schedule')]
        after = [('core', '0024_daily_sheet_commission_snapshot')]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            user = apps.get_model('core', 'User').objects.create(email='migration@example.com')
            agency = apps.get_model('core', 'Agency').objects.create(name='Migration', code='migration')
            model = apps.get_model('core', 'DailySheet')
            for index, state in enumerate(['DRAFT', 'SUBMITTED', 'APPROVED', 'RETURNED', 'REOPENED'], 1):
                model.objects.create(agency_id=agency.pk, created_by_id=user.pk, transaction_date=date(2026, 8, index), status=state, incoming_funds=Decimal('9500.10'), tax=Decimal('12.34'))
            original = list(model.objects.order_by('pk').values())
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            current = executor.loader.project_state(after).apps.get_model('core', 'DailySheet')
            migrated = list(current.objects.order_by('pk').values())
            for row in migrated:
                self.assertEqual(row.pop('commission_rate_snapshot'), Decimal('.05'))
            self.assertEqual(original, migrated)
            created = current.objects.create(agency_id=agency.pk, created_by_id=user.pk, transaction_date=date(2026, 9, 1))
            self.assertEqual(created.commission_rate_snapshot, Decimal('.02'))
            snapshots = list(current.objects.order_by('pk').values())
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            self.assertEqual(snapshots, list(current.objects.order_by('pk').values()))
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
