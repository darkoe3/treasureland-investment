import json
from unittest.mock import patch

from django.contrib.auth import get_user
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory, TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from core.models import AuditLog, User


class PasswordChangeSecurityTests(TestCase):
    url = '/api/profile/change-password/'
    original_password = 'Initial-security-pass-987!'
    strong_password = 'Fjord!Copper_7392-River'

    def setUp(self):
        self.user = User.objects.create_user(
            'distinctiveaccount@example.com', self.original_password,
            full_name='Distinctive Account',
        )
        self.refresh_tokens = [RefreshToken.for_user(self.user) for _ in range(2)]
        self.access_tokens = [str(token.access_token) for token in self.refresh_tokens]
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + self.access_tokens[0])
        self.original_hash = self.user.password
        self.payload = {
            'current_password': self.original_password,
            'new_password': self.strong_password,
            'confirm_password': self.strong_password,
        }

    def assert_no_secrets(self, value, payload):
        serialized = json.dumps(value, default=str)
        for secret in [*payload.values(), self.original_hash, self.user.password]:
            self.assertNotIn(secret, serialized)

    def assert_rejected(self, payload, field):
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(field, response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, self.original_hash)
        self.assertTrue(self.user.check_password(self.original_password))
        self.assertFalse(AuditLog.objects.filter(action='PASSWORD_CHANGED').exists())
        self.assertFalse(BlacklistedToken.objects.exists())
        self.assertEqual(self.client.get('/api/profile/').status_code, 200)
        self.assert_no_secrets(response.data, payload)

    def test_authentication_required(self):
        self.client.credentials()
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 401)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, self.original_hash)
        self.assertFalse(AuditLog.objects.filter(action='PASSWORD_CHANGED').exists())
        self.assert_no_secrets(response.data, self.payload)

    def test_incorrect_current_password(self):
        self.assert_rejected({**self.payload, 'current_password': 'Incorrect-current-912!'}, 'current_password')

    def test_confirmation_mismatch(self):
        self.assert_rejected({**self.payload, 'confirm_password': 'Mismatch-confirmation-831!'}, 'confirm_password')

    def test_common_short_and_numeric_passwords(self):
        for password in ['password123', 'aB!2', '948572619384']:
            with self.subTest(policy=password):
                self.assert_rejected({**self.payload, 'new_password': password, 'confirm_password': password}, 'new_password')

    def test_password_similar_to_user_email(self):
        self.assert_rejected({**self.payload, 'new_password': self.user.email, 'confirm_password': self.user.email}, 'new_password')

    def test_direct_policy_validation_precedes_password_update(self):
        with patch('core.audit_profile.validate_password', side_effect=ValidationError('Password policy rejected this choice.')) as validate, patch.object(User, 'set_password') as set_password:
            self.assert_rejected(self.payload, 'new_password')
            validate.assert_called_once_with(self.strong_password, self.user)
            set_password.assert_not_called()

    def test_strong_password_revokes_all_old_tokens_and_sessions_without_audit_secrets(self):
        other = User.objects.create_user('other-security@example.com', 'Separate-account-421!', full_name='Other')
        other_refresh = RefreshToken.for_user(other)
        session_clients = [Client(), Client()]
        for session_client in session_clients:
            session_client.force_login(self.user)
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['reauthenticate'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.strong_password))
        self.assertFalse(self.user.check_password(self.original_password))
        self.assert_no_secrets(response.data, self.payload)
        for token, access in zip(self.refresh_tokens, self.access_tokens):
            self.assertTrue(BlacklistedToken.objects.filter(token__jti=token['jti']).exists())
            self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + access)
            self.assertEqual(self.client.get('/api/profile/').status_code, 401)
            self.client.credentials()
            self.assertEqual(self.client.post('/api/auth/refresh/', {'refresh': str(token)}, format='json').status_code, 401)
        for session_client in session_clients:
            request = RequestFactory().get('/admin/')
            request.session = session_client.session
            self.assertFalse(get_user(request).is_authenticated)
        self.assertFalse(BlacklistedToken.objects.filter(token__jti=other_refresh['jti']).exists())
        events = list(AuditLog.objects.filter(action='PASSWORD_CHANGED').values())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['new_values'], {'changed_fields': ['password']})
        self.assertEqual(events[0]['old_values'], {})
        self.assertEqual(events[0]['description'], '')
        self.assert_no_secrets(events, self.payload)
        for forbidden in ['current_password', 'new_password', 'confirm_password', 'password_hash']:
            self.assertNotIn(forbidden, json.dumps(events, default=str))
        login = self.client.post('/api/auth/login/', {'email': self.user.email, 'password': self.strong_password}, format='json')
        self.assertEqual(login.status_code, 200)
