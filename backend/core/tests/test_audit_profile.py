import json
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import User, Agency, AuditLog, UserAgencyAssignment


class AuditProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser('admin@example.com', 'Initial-pass-987!', full_name='Admin')
        self.user = User.objects.create_user('user@example.com', 'Initial-pass-987!', full_name='Accountant')
        self.agency = Agency.objects.create(name='Agency One', code='one')
        self.client.force_authenticate(self.admin)
        self.event = AuditLog.objects.create(user=self.user, agency=self.agency, action='SHEET_CREATED', model_name='DailySheet', object_id='123', old_values={'password': 'SECRET', 'actor_id': self.user.pk, 'nested': {'token': 'SECRET'}}, new_values={'request_body': 'SECRET', 'changed_fields': ['full_name', 'SECRET'], 'is_active': True}, description='SECRET personal data')

    def test_permissions_and_read_only(self):
        for user in [self.user, self.admin]:
            self.client.force_authenticate(user)
            for path in ['/api/audit-logs/', f'/api/audit-logs/{self.event.pk}/', '/api/audit-logs/export/']:
                self.assertEqual(self.client.get(path).status_code, 200 if user == self.admin else 403)
            for method in ['post', 'put', 'patch', 'delete']:
                path = '/api/audit-logs/' if method == 'post' else f'/api/audit-logs/{self.event.pk}/'
                self.assertEqual(getattr(self.client, method)(path, {}, format='json').status_code, 405 if user == self.admin else 403)

    def test_filters_pagination_redaction_unchanged(self):
        before = list(AuditLog.objects.values())
        second = AuditLog.objects.create(user=self.admin, action='IMPORT_FAILED', model_name='Import', object_id='456')
        data = self.client.get('/api/audit-logs/?page_size=1').data
        self.assertEqual(data['count'], 2)
        self.assertEqual(data['results'][0]['id'], second.pk)
        self.assertIsNotNone(data['next'])
        for query in [f'agency={self.agency.pk}', 'search=Accountant', 'search=123', 'action=SHEET_CREATED', 'model_name=DailySheet', 'role=ACCOUNTANT', f'user={self.user.pk}', 'result=SUCCESS']:
            result = self.client.get('/api/audit-logs/?' + query)
            self.assertEqual(result.status_code, 200)
            self.assertEqual([row['id'] for row in result.data['results']], [self.event.pk])
        today = timezone.localdate().isoformat()
        self.assertEqual(self.client.get(f'/api/audit-logs/?date_from={today}&date_to={today}').data['count'], 2)
        self.assertEqual(self.client.get('/api/audit-logs/?date_to=2000-01-01').data['count'], 0)
        for query in ['agency=invalid', 'date_from=bad', 'date_from=2026-02-02&date_to=2026-01-01']:
            self.assertEqual(self.client.get('/api/audit-logs/?' + query).status_code, 400)
        detail = self.client.get(f'/api/audit-logs/{self.event.pk}/').data
        self.assertNotIn('SECRET', json.dumps(detail))
        self.assertEqual(detail['metadata']['before'], {'actor_id': self.user.pk})
        self.assertEqual(before[0], AuditLog.objects.values().get(pk=self.event.pk))

    def test_export_filters_and_formula_safety(self):
        self.user.full_name = '=HYPERLINK("bad")'
        self.user.save()
        response = self.client.get('/api/audit-logs/export/?action=SHEET_CREATED')
        self.assertEqual(response.status_code, 200)
        self.assertIn("'=HYPERLINK", response.content.decode())
        self.assertNotIn('SECRET', response.content.decode())
        self.assertEqual(len(self.client.get('/api/audit-logs/export/?action=NONE').content.decode().splitlines()), 1)

    def test_self_profile_and_validation(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f'/api/profile/?user={self.admin.pk}').data['id'], self.user.pk)
        self.assertEqual(self.client.patch('/api/profile/', {'full_name': 'Updated Name'}, format='json').status_code, 200)
        for payload in [{'full_name': ''}, {'full_name': 'x' * 256}, {'full_name': '\x01'}, {'email': 'bad'}, {'role': 'SUPER_ADMIN'}, {'agencies': [1]}, {'is_active': False}, {'id': self.admin.pk}, {'agency_assignments': []}]:
            self.assertEqual(self.client.patch('/api/profile/', payload, format='json').status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, 'ACCOUNTANT')
        self.assertEqual(self.user.email, 'user@example.com')
        self.assertEqual(self.client.patch(f'/api/profile/{self.admin.pk}/', {'full_name': 'Hacked'}).status_code, 404)
        event = AuditLog.objects.get(action='PROFILE_UPDATED')
        self.assertEqual(event.new_values, {'changed_fields': ['full_name']})
        self.assertNotIn('Updated Name', json.dumps(event.new_values))

    def test_password_validation_and_revocation(self):
        refresh = RefreshToken.for_user(self.user)
        access = str(refresh.access_token)
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + access)
        valid = {'current_password': 'Initial-pass-987!', 'new_password': 'Updated-pass-321!', 'confirm_password': 'Updated-pass-321!'}
        for payload, field in [({k: v for k, v in valid.items() if k != 'current_password'}, 'current_password'), ({**valid, 'current_password': 'wrong'}, 'current_password'), ({**valid, 'confirm_password': 'wrong'}, 'confirm_password'), ({**valid, 'new_password': '123', 'confirm_password': '123'}, 'new_password')]:
            response = self.client.post('/api/profile/change-password/', payload, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertIn(field, response.data)
        self.assertEqual(self.client.post('/api/profile/change-password/', valid, format='json').status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(valid['new_password']))
        self.assertEqual(self.client.get('/api/profile/').status_code, 401)
        self.assertEqual(self.client.post('/api/auth/refresh/', {'refresh': str(refresh)}).status_code, 401)
        event = AuditLog.objects.get(action='PASSWORD_CHANGED')
        self.assertEqual(event.new_values, {'changed_fields': ['password']})
        self.assertNotIn('pass-', json.dumps(event.new_values))
        self.client.credentials()
        login = self.client.post('/api/auth/login/', {'email': self.user.email, 'password': valid['new_password']})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='LOGIN_SUCCESS', user=self.user).exists())

    def test_anonymous_denied(self):
        self.client.force_authenticate(None)
        for path in ['/api/profile/', '/api/audit-logs/', '/api/audit-logs/export/']:
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_scoped_sheet_history_and_assignment_events(self):
        from core.models import DailySheet
        sheet = DailySheet.objects.create(agency=self.agency, transaction_date=timezone.localdate(), created_by=self.admin)
        AuditLog.objects.create(user=self.admin, agency=self.agency, daily_sheet=sheet, action='SHEET_CREATED', model_name='DailySheet', object_id=str(sheet.pk))
        assignment = UserAgencyAssignment.objects.create(user=self.user, agency=self.agency, can_view_history=True)
        self.client.force_authenticate(self.user)
        path = f'/api/daily-sheets/{sheet.pk}/history/'
        self.assertEqual(self.client.get(path).data['count'], 1)
        self.assertEqual(self.client.get('/api/audit-logs/?agency=' + str(self.agency.pk)).status_code, 403)
        self.assertEqual(self.client.get(path + '?agency=999&daily_sheet=999').status_code, 404)
        assignment.can_view_history = False
        assignment.save()
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_export_limit(self):
        from unittest.mock import patch
        with patch('django.db.models.query.QuerySet.count', return_value=10001):
            response = self.client.get('/api/audit-logs/export/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('10,000', str(response.data))

    def test_legacy_metadata_allowlist(self):
        from core.audit_profile import safe_metadata
        secrets = {'password': 'secret', 'password_hash': 'secret', 'token': 'secret', 'cookie': 'secret', 'csrf': 'secret', 'request_body': 'secret', 'database_url': 'secret', 'secret_key': 'secret', 'workbook': 'secret', 'card_number': 'secret', 'traceback': 'secret', 'email': 'secret', 'actor_id': 'secret', 'is_active': 'secret', 'changed_fields': ['secret'], 'nested': {'agency_id': 1}}
        self.assertEqual(safe_metadata(secrets), {'changed_fields': []})
        self.assertEqual(safe_metadata(['secret']), {})

    def test_login_logout_and_noop_profile_events(self):
        self.client.force_authenticate(None)
        login = self.client.post('/api/auth/login/', {'email': self.user.email, 'password': 'Initial-pass-987!'})
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + login.data['access'])
        self.assertIsNotNone(self.client.get('/api/profile/').data['last_login'])
        self.assertEqual(self.client.patch('/api/profile/', {'full_name': self.user.full_name}).status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action='PROFILE_UPDATED').exists())
        foreign = RefreshToken.for_user(self.admin)
        self.assertEqual(self.client.post('/api/auth/logout/', {'refresh': str(foreign)}).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/logout/', {'refresh': login.data['refresh']}).status_code, 204)
        self.assertEqual(AuditLog.objects.filter(action='LOGOUT', user=self.user).count(), 1)
