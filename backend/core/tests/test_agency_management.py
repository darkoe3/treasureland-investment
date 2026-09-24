from datetime import date, timedelta
from django.utils import timezone
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.db import close_old_connections, IntegrityError, transaction
from concurrent.futures import ThreadPoolExecutor
from rest_framework.test import APIClient
from core.models import TPMDailyTransaction, DailySheetImportBatch, TerminalImportBatch, Agency, AuditLog, DailySheet, Person, TPMCode, TerminalNumber, User, UserAgencyAssignment


class AgencyManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('agency-admin@example.com', 'StrongPass123!', full_name='Admin', role='SUPER_ADMIN')
        self.accountant = User.objects.create_user('agency-acct@example.com', 'StrongPass123!', full_name='Accountant')
        self.agency = Agency.objects.create(name='Musa', code='MUSA')
        self.other = Agency.objects.create(name='Other', code='OTHER')
        self.assignment = UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True, can_edit=True, can_view_history=True, can_export=True)
        self.person = Person.objects.create(agency=self.agency, full_name='Agent', agent_type='SUBAGENT')
        self.code = TPMCode.objects.create(person=self.person, code='SUB1')
        self.terminal = TerminalNumber.objects.create(agency=self.agency, person=self.person, sub_agent_number=self.code, terminal_number='T1', created_by=self.admin, updated_by=self.admin)
        self.sheet = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 9, 21), created_by=self.admin)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f'/api/agencies/{self.agency.pk}/'

    def change(self, action='deactivate', **overrides):
        return self.client.post(self.url + action + '/', {'reason': 'Operational review', 'confirmed': True, 'acknowledge_editable_sheets': True, **overrides}, format='json')

    def test_create_normalizes_and_case_insensitive_uniqueness(self):
        response = self.client.post('/api/agencies/', {'name': '  New Agency  ', 'code': ' NEW_1 '}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'New Agency')
        self.assertEqual(response.data['code'], 'NEW_1')
        self.assertTrue(response.data['is_active'])
        for data, field in [({'name': 'new agency', 'code': 'UNIQUE'}, 'name'), ({'name': 'Unique', 'code': 'new_1'}, 'code'), ({'name': ' ', 'code': 'x'}, 'name'), ({'name': 'x', 'code': 'bad/code'}, 'code')]:
            response = self.client.post('/api/agencies/', data, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)
        self.assertTrue(AuditLog.objects.filter(action='AGENCY_CREATED').exists())

    def test_accountant_denied_mutations_and_scoped_reads(self):
        self.client.force_authenticate(self.accountant)
        for method, url, data in [('post', '/api/agencies/', {}), ('patch', self.url, {'name': 'Changed'}), ('post', self.url+'deactivate/', {}), ('post', self.url+'reactivate/', {})]:
            self.assertEqual(getattr(self.client, method)(url, data, format='json').status_code, 403)
        result = self.client.get('/api/agencies/').data
        self.assertEqual([row['id'] for row in result], [self.agency.pk])
        self.assertEqual(result[0]['counts']['people'], 1)
        for suffix in ['', 'impact/']:
            self.assertEqual(self.client.get(f'/api/agencies/{self.other.pk}/{suffix}').status_code, 404)

    def test_database_case_insensitive_constraints(self):
        for data in [{"name": "musa", "code": "UNIQUE"}, {"name": "Unique", "code": "musa"}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Agency.objects.create(**data)

    def test_edit_confirmation_identity_and_relationships(self):
        entry = TPMDailyTransaction.objects.create(daily_sheet=self.sheet, tpm_code=self.code,
            created_by=self.admin, updated_by=self.admin)
        snapshots = (entry.person_id_snapshot, entry.person_name_snapshot, entry.tpm_code_snapshot, entry.terminal_number_snapshot)
        self.assertEqual(self.client.patch(self.url, {'code': 'NEW'}, format='json').status_code, 400)
        result = self.client.patch(self.url, {'name': 'Renamed', 'code': 'NEW', 'confirm_code_change': True}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data['id'], self.agency.pk)
        self.assertEqual(self.client.patch(self.url, {'is_active': False}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertEqual(self.agency.people.count(), 1)
        self.assertEqual(self.agency.daily_sheets.count(), 1)
        self.assertEqual(self.agency.user_assignments.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='AGENCY_UPDATED').exists())
        entry.refresh_from_db()
        self.assertEqual(snapshots, (entry.person_id_snapshot, entry.person_name_snapshot, entry.tpm_code_snapshot, entry.terminal_number_snapshot))

    def test_lifecycle_requires_reason_confirmation_and_draft_ack(self):
        for overrides, field in [({'reason': ' '}, 'reason'), ({'confirmed': False}, 'confirmed'), ({'acknowledge_editable_sheets': False}, 'acknowledge_editable_sheets')]:
            response = self.change(**overrides)
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)
        self.assertEqual(self.change().status_code, 200)
        self.assertEqual(self.change().status_code, 409)
        self.assertEqual(self.change('reactivate', reason='').status_code, 400)
        self.assertEqual(self.change('reactivate', confirmed=False).status_code, 400)
        self.person.is_active = False
        self.person.save()
        self.assertEqual(self.change('reactivate').status_code, 200)
        self.person.refresh_from_db()
        self.assertFalse(self.person.is_active)
        self.assignment.refresh_from_db()
        self.assertTrue(self.assignment.can_create)

    def test_deactivation_preserves_records_and_safe_audit(self):
        before = [model.objects.count() for model in [Person, TPMCode, TerminalNumber, DailySheet, UserAgencyAssignment]]
        self.assertEqual(self.change().status_code, 200)
        self.assertEqual(before, [model.objects.count() for model in [Person, TPMCode, TerminalNumber, DailySheet, UserAgencyAssignment]])
        event = AuditLog.objects.get(action='AGENCY_DEACTIVATED')
        self.assertEqual(set(event.new_values), {'agency_id', 'name', 'code', 'is_active', 'actor_id', 'reason', 'impact'})
        self.assertEqual(event.new_values['impact']['editable_daily_sheets'], 1)
        self.assertEqual(event.old_values['is_active'], True)
        self.terminal.refresh_from_db()
        self.assertTrue(self.terminal.is_active)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(f'/api/daily-sheets/{self.sheet.pk}/').status_code, 200)
        self.client.force_authenticate(self.admin)  # Reports retain existing Super Admin policy.
        response = self.client.get('/api/reports/agency-summary/', {'agency': self.agency.pk, 'period': 'daily', 'date': '2026-09-21'})
        self.assertEqual(response.status_code, 200, response.data)

    def test_previewed_imports_cannot_confirm_after_deactivation(self):
        common = dict(uploader=self.admin, agency=self.agency, original_filename="test.xlsx",
                      file_hash="a" * 64, expires_at=timezone.now() + timedelta(hours=1))
        daily = DailySheetImportBatch.objects.create(**common, transaction_date=date(2026, 9, 22))
        registers = [TerminalImportBatch.objects.create(**common, preview_payload={"register_type": kind})
                     for kind in ("TERMINAL", "SUB_AGENT")]
        self.change()
        urls = [f"/api/daily-sheet-imports/{daily.pk}/confirm/"] + [
            f"/api/terminal-number-imports/{batch.pk}/confirm/" for batch in registers]
        for url in urls:
            response = self.client.post(url, {"confirmed": True, "reason": "Import", "warnings_acknowledged": True}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        for batch in [daily, *registers]:
            batch.refresh_from_db()
            self.assertEqual(batch.status, "PREVIEWED")

    def test_inactive_accountant_assignment_paths_and_history_permission(self):
        self.change()
        response = self.client.post(f"/api/accountants/{self.accountant.pk}/set-agencies/",
            {"agency_assignments": [{"agency": self.agency.pk}]}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/accountants/', {
            "email": "new@example.com", "full_name": "New", "password": "StrongPass123!",
            "agency_assignments": [{"agency": self.agency.pk}]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assignment.can_view_history = False
        self.assignment.save()
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(self.url).data["recent_audit_events"], [])

    def test_inactive_rejects_writes_and_imports(self):
        self.change()
        attempts = [('/api/daily-sheets/', {'agency': self.agency.pk, 'transaction_date': '2026-09-22'}),
            ('/api/people/', {'agency': self.agency.pk, 'full_name': 'New', 'agent_type': 'SUBAGENT', 'is_active': False}),
            ('/api/tpm-codes/', {'person': self.person.pk, 'code': 'SUB2', 'is_active': False}),
            ('/api/terminal-numbers/', {'agency': self.agency.pk, 'person': self.person.pk, 'sub_agent_number': self.code.pk, 'terminal_number': 'T2', 'is_active': False}),
            ('/api/agency-assignments/', {'user': self.accountant.pk, 'agency': self.other.pk}),
            ('/api/daily-sheet-imports/preview/', {'agency': self.agency.pk}),
            ('/api/terminal-number-imports/preview/', {'agency': self.agency.pk, 'register_type': 'TERMINAL'}),
            ('/api/terminal-number-imports/preview/', {'agency': self.agency.pk, 'register_type': 'SUB_AGENT'})]
        self.other.is_active = False
        self.other.save()
        for url, data in attempts:
            response = self.client.post(url, data, format='json')
            self.assertEqual(response.status_code, 400, (url, response.data))
        for url in [f'/api/people/{self.person.pk}/', f'/api/tpm-codes/{self.code.pk}/']:
            self.assertEqual(self.client.patch(url, {'is_active': True}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f'/api/terminal-numbers/{self.terminal.pk}/reactivate/', {'confirmed': True, 'reason': 'test'}, format='json').status_code, 400)


class ConcurrentAgencyStatusTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_deactivations_produce_one_event(self):
        agency = Agency.objects.create(name='Concurrent', code='CONCURRENT')
        admin = User.objects.create_user('concurrent@example.com', 'StrongPass123!', full_name='Admin', role='SUPER_ADMIN')
        def deactivate(_):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(admin)
                return client.post(f'/api/agencies/{agency.pk}/deactivate/', {'reason': 'test', 'confirmed': True}, format='json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(deactivate, range(2))), [200, 409])
        self.assertEqual(AuditLog.objects.filter(action='AGENCY_DEACTIVATED').count(), 1)
