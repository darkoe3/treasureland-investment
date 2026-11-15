from datetime import date
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import OrganisationSettings, User, AuditLog, DailySheet, PayerPayment, PaymentObligation
from core.tests.test_payment_games import GameFixture

URL = '/api/organisation-settings/'


class OrganisationSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('settings@example.com', 'Password123!', full_name='Admin')
        self.accountant = User.objects.create_user('accountant@example.com', 'Password123!', full_name='Accountant')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_defaults_and_singleton(self):
        data = self.client.get(URL).data
        self.assertEqual(data['display_name'], 'Treasureland Investment Limited')
        self.assertEqual(data['timezone'], 'Africa/Lagos')
        self.assertEqual(data['date_format'], 'YYYY-MM-DD')
        self.assertEqual(data['financial_policy']['currency'], 'NGN')
        self.assertEqual(data['financial_policy']['commission_rate'], '0.02')
        self.assertFalse(OrganisationSettings.objects.exists())
        self.assertEqual(self.client.patch(URL, {'display_name': 'New organisation'}, format='json').status_code, 200)
        self.assertEqual(self.client.get(URL).data['display_name'], 'New organisation')
        self.client.patch(URL, {'address': 'Office'}, format='json')
        self.assertEqual(OrganisationSettings.objects.count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganisationSettings.objects.create(pk=2)

    def test_permissions_methods_and_profile(self):
        for user, expected in [(self.accountant, 403), (None, 401)]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(URL).status_code, expected)
            self.assertEqual(self.client.patch(URL, {}, format='json').status_code, expected)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get('/api/profile/').status_code, 200)
        self.client.force_authenticate(self.admin)
        for method in ['post', 'put', 'delete']:
            self.assertEqual(getattr(self.client, method)(URL, {}, format='json').status_code, 405)
        self.assertFalse(OrganisationSettings.objects.exists())

    def test_validation_rejects_unsupported_and_financial_fields(self):
        for key in ['id', 'currency', 'currency_symbol', 'commission_rate', 'commission_rate_snapshot', 'financial_policy', 'amount_received', 'receipt_number', 'game_schedule', 'unknown']:
            response = self.client.patch(URL, {key: 'changed', 'display_name': 'Must not save'}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn(key, response.data)
        for key, value in [('display_name', ''), ('display_name', 'a' * 161), ('address', 'a' * 501), ('contact_email', 'bad'), ('telephone', '<script>'), ('timezone', 'Invalid/Zone'), ('date_format', '%x'), ('receipt_heading', 'bad\x00'), ('receipt_footer', 'a' * 501)]:
            response = self.client.patch(URL, {key: value}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn(key, response.data)
        self.assertFalse(OrganisationSettings.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_audit_is_safe_and_immutable(self):
        values = {'address': 'Private office', 'contact_email': 'private@example.com', 'telephone': '+234 12345678', 'timezone': 'Africa/Accra', 'date_format': 'DD/MM/YYYY', 'receipt_heading': 'Approved heading', 'receipt_footer': 'Approved footer'}
        self.assertEqual(self.client.patch(URL, values, format='json').status_code, 200)
        event = AuditLog.objects.get()
        self.assertEqual(event.action, 'ORGANISATION_SETTINGS_UPDATED')
        self.assertEqual(event.new_values, {'changed_fields': sorted(values), 'actor_id': self.admin.pk})
        self.assertEqual(event.old_values, {})
        self.assertEqual(event.description, '')
        self.assertEqual(event.object_id, '1')
        self.assertIsNotNone(event.created_at)
        data = self.client.get(f'/api/audit-logs/{event.pk}/').data
        self.assertEqual(data['metadata']['after'], event.new_values)
        self.assertEqual(self.client.patch(f'/api/audit-logs/{event.pk}/', {}, format='json').status_code, 405)
        self.client.patch(URL, values, format='json')
        self.assertEqual(AuditLog.objects.count(), 1)


class SettingsReceiptTests(GameFixture, TestCase):
    def test_receipt_presentation_and_historical_snapshots(self):
        obligation_id = self.create().data['id']
        payment_id = self.pay(obligation_id, 'settings-receipt').data['id']
        sheet = DailySheet.objects.create(agency=self.agency, created_by=self.admin, transaction_date=date(2026, 11, 9), commission_rate_snapshot=Decimal('.05'))
        payment_before = PayerPayment.objects.values().get(pk=payment_id)
        obligation_before = PaymentObligation.objects.values().get(pk=obligation_id)
        sheet_before = DailySheet.objects.values().get(pk=sheet.pk)
        path = f'/api/payer-payments/{payment_id}/receipt/'
        self.assertEqual(self.client.get(path).status_code, 200)
        values = {'display_name': 'Approved Organisation', 'address': 'Approved Office', 'telephone': '+234 12345678', 'contact_email': 'receipts@example.com', 'receipt_heading': 'Approved Receipt', 'receipt_footer': 'Approved Footer', 'timezone': 'Africa/Accra', 'date_format': 'DD/MM/YYYY'}
        self.assertEqual(self.client.patch(URL, values, format='json').status_code, 200)
        receipt = self.client.get(path)
        self.assertEqual(receipt.status_code, 200)
        for value in list(values.values())[:6]:
            self.assertIn(value.encode(), receipt.content)
        self.assertIn(b'Approved Footer', receipt.content)
        self.assertIn(payment_before['payment_date'].isoformat().encode(), receipt.content)
        self.assertIn(payment_before['receipt_number'].encode(), receipt.content)
        self.assertIn(payment_before['game_snapshot']['name'].encode(), receipt.content)
        self.assertEqual(PayerPayment.objects.values().get(pk=payment_id), payment_before)
        self.assertEqual(PaymentObligation.objects.values().get(pk=obligation_id), obligation_before)
        self.assertEqual(DailySheet.objects.values().get(pk=sheet.pk), sheet_before)
        self.assertEqual(sheet.commission_for('100'), Decimal('5'))
        new_id = self.pay(obligation_id, 'after-settings').data['id']
        self.assertIn(b'Approved Receipt', self.client.get(f'/api/payer-payments/{new_id}/receipt/').content)
        # ReportLab markup must be escaped, never interpreted as tags or links.
        self.client.patch(URL, {'receipt_heading': '<b>Plain text</b> & only'}, format='json')
        self.assertEqual(self.client.get(path).status_code, 200)
