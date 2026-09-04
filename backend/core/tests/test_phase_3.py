from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import (
    Agency,
    AuditLog,
    DailySheet,
    Person,
    TPMCode,
    UserAgencyAssignment,
    UserRole,
)


User = get_user_model()


class DeploymentReadinessTests(SimpleTestCase):
    def test_health_endpoint_is_public_and_minimal(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_static_files_are_configured_for_whitenoise(self):
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", settings.MIDDLEWARE)
        self.assertEqual(
            settings.STORAGES["staticfiles"]["BACKEND"],
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
        )

    def test_production_security_settings_are_environment_driven(self):
        self.assertEqual(settings.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertIsInstance(settings.ALLOWED_HOSTS, list)
        self.assertIsInstance(settings.CSRF_TRUSTED_ORIGINS, list)


class Phase3APITests(APITestCase):
    def setUp(self):
        self.super_admin = User.objects.create_superuser("admin@example.com", "AdminPass123!", full_name="Admin")
        self.accountant = User.objects.create_user("acct@example.com", "AcctPass123!", full_name="Acct")
        self.agency_one = Agency.objects.create(name="Musa 1", code="musa-1")
        self.agency_two = Agency.objects.create(name="Sango", code="sango")
        self.assignment_one = UserAgencyAssignment.objects.create(
            user=self.accountant,
            agency=self.agency_one,
            can_create=True,
            can_edit=False,
            can_delete=False,
            can_export=True,
            can_view_history=True,
            assigned_by=self.super_admin,
        )
        self.assignment_two = UserAgencyAssignment.objects.create(
            user=self.accountant,
            agency=self.agency_two,
            can_create=False,
            can_edit=True,
            can_delete=False,
            can_export=False,
            can_view_history=False,
            assigned_by=self.super_admin,
        )

    def test_current_user_response_for_super_admin(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], UserRole.SUPER_ADMIN)
        self.assertEqual(len(response.data["active_agencies"]), 2)
        self.assertEqual(response.data["agency_assignments"], [])

    def test_current_user_response_for_accountant_with_multiple_agencies(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], UserRole.ACCOUNTANT)
        self.assertEqual(len(response.data["agency_assignments"]), 2)
        first = response.data["agency_assignments"][0]
        self.assertIn("agency", first)
        self.assertIn("can_create", first)

    def test_current_user_response_excludes_sensitive_fields(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.get("/api/auth/me/")
        payload = str(response.data)
        self.assertNotIn("password", payload)
        self.assertNotIn("token", payload.lower())
        self.assertNotIn("is_superuser", payload)

    def test_only_super_admin_can_list_accountants(self):
        self.client.force_authenticate(self.accountant)
        blocked = self.client.get("/api/accountants/")
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.super_admin)
        allowed = self.client.get("/api/accountants/")
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)

    def test_only_super_admin_can_create_accountant_and_password_is_hashed(self):
        self.client.force_authenticate(self.accountant)
        blocked = self.client.post("/api/accountants/", {"email": "new@example.com", "full_name": "New", "password": "StrongPass123!"})
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.super_admin)
        allowed = self.client.post("/api/accountants/", {"email": "new@example.com", "full_name": "New", "password": "StrongPass123!"})
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="new@example.com")
        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.role, UserRole.ACCOUNTANT)

    def test_weak_passwords_are_rejected(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.post("/api/accountants/", {"email": "weak@example.com", "full_name": "Weak", "password": "123"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())

    def test_duplicate_email_addresses_are_rejected_case_insensitively(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.post("/api/accountants/", {"email": "ACCT@example.com", "full_name": "Dup", "password": "StrongPass123!"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accountant_admin_action_urls_resolve_to_hyphenated_routes(self):
        action_names = {
            "set-agencies": "accountant-set-agencies",
            "reset-password": "accountant-reset-password",
            "activate": "accountant-activate",
            "deactivate": "accountant-deactivate",
        }
        for action, route_name in action_names.items():
            with self.subTest(action=action):
                path = f"/api/accountants/{self.accountant.id}/{action}/"
                self.assertEqual(resolve(path).url_name, route_name)
                self.assertEqual(reverse(route_name, kwargs={"pk": self.accountant.id}), path)

    def test_super_admin_can_assign_multiple_agencies_atomically(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.post(
            f"/api/accountants/{self.accountant.id}/set-agencies/",
            {
                "agency_assignments": [
                    {"agency": self.agency_one.id, "can_create": True, "can_edit": True, "can_delete": False, "can_export": False, "can_view_history": True},
                    {"agency": self.agency_two.id, "can_create": False, "can_edit": False, "can_delete": True, "can_export": True, "can_view_history": False},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.accountant.agency_assignments.count(), 2)
        one = self.accountant.agency_assignments.get(agency=self.agency_one)
        two = self.accountant.agency_assignments.get(agency=self.agency_two)
        self.assertTrue(one.can_create)
        self.assertTrue(one.can_edit)
        self.assertFalse(one.can_export)
        self.assertTrue(two.can_delete)
        self.assertTrue(two.can_export)
        assignments = {item["agency"]["id"]: item for item in response.data["agency_assignments"]}
        self.assertEqual(set(assignments), {self.agency_one.id, self.agency_two.id})
        self.assertTrue(assignments[self.agency_one.id]["can_create"])
        self.assertTrue(assignments[self.agency_one.id]["can_edit"])
        self.assertFalse(assignments[self.agency_one.id]["can_delete"])
        self.assertFalse(assignments[self.agency_one.id]["can_export"])
        self.assertTrue(assignments[self.agency_one.id]["can_view_history"])
        self.assertFalse(assignments[self.agency_two.id]["can_create"])
        self.assertFalse(assignments[self.agency_two.id]["can_edit"])
        self.assertTrue(assignments[self.agency_two.id]["can_delete"])
        self.assertTrue(assignments[self.agency_two.id]["can_export"])
        self.assertFalse(assignments[self.agency_two.id]["can_view_history"])
        read_response = self.client.get(f"/api/accountants/{self.accountant.id}/")
        self.assertEqual(read_response.status_code, status.HTTP_200_OK)
        read_assignments = {item["agency"]["id"]: item for item in read_response.data["agency_assignments"]}
        self.assertEqual(read_assignments, assignments)
        self.assertTrue(AuditLog.objects.filter(action="ACCOUNTANT_AGENCIES_SET").exists())

    def test_duplicate_assignments_are_prevented(self):
        self.client.force_authenticate(self.super_admin)
        response = self.client.post(
            f"/api/accountants/{self.accountant.id}/set-agencies/",
            {
                "agency_assignments": [
                    {"agency": self.agency_one.id},
                    {"agency": self.agency_one.id},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.accountant.agency_assignments.count(), 2)

    def test_accountant_cannot_alter_their_own_role(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.patch(f"/api/accountants/{self.accountant.id}/", {"role": UserRole.SUPER_ADMIN})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.accountant.refresh_from_db()
        self.assertEqual(self.accountant.role, UserRole.ACCOUNTANT)

    def test_accountant_role_is_denied_administrative_accountant_actions(self):
        self.client.force_authenticate(self.accountant)
        post_actions = {
            "set-agencies": {"agency_assignments": [{"agency": self.agency_one.id, "can_create": True}]},
            "reset-password": {"password": "NewStrongPass123!"},
            "activate": {},
            "deactivate": {},
        }
        for action, payload in post_actions.items():
            with self.subTest(action=action):
                response = self.client.post(f"/api/accountants/{self.accountant.id}/{action}/", payload, format="json")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_deactivated_accountant_cannot_authenticate(self):
        self.accountant.is_active = False
        self.accountant.save()
        response = self.client.post("/api/auth/login/", {"email": "acct@example.com", "password": "AcctPass123!"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deactivation_preserves_historical_records(self):
        sheet = DailySheet.objects.create(
            agency=self.agency_one,
            transaction_date=date(2026, 8, 27),
            incoming_funds=Decimal("0.00"),
            tax=Decimal("0.00"),
            created_by=self.accountant,
        )
        self.client.force_authenticate(self.super_admin)
        response = self.client.post(f"/api/accountants/{self.accountant.id}/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(DailySheet.objects.filter(pk=sheet.pk, created_by=self.accountant).exists())

    def test_password_reset_uses_validation_and_hashing(self):
        self.client.force_authenticate(self.super_admin)
        weak = self.client.post(f"/api/accountants/{self.accountant.id}/reset-password/", {"password": "123"})
        self.assertEqual(weak.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", weak.data)
        strong = self.client.post(f"/api/accountants/{self.accountant.id}/reset-password/", {"password": "NewStrongPass123!"})
        self.assertEqual(strong.status_code, status.HTTP_200_OK)
        self.accountant.refresh_from_db()
        self.assertTrue(self.accountant.check_password("NewStrongPass123!"))

    def test_unauthorized_accountant_management_requests_are_rejected(self):
        response = self.client.get("/api/accountants/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_agency_filtering_remains_enforced(self):
        Person.objects.create(agency=self.agency_one, full_name="Visible", agent_type="MAIN_AGENT")
        Person.objects.create(agency=Agency.objects.create(name="Hidden", code="hidden"), full_name="Hidden", agent_type="MAIN_AGENT")
        self.client.force_authenticate(self.accountant)
        response = self.client.get("/api/people/")
        data = response.data["results"] if "results" in response.data else response.data
        names = {item["full_name"] for item in data}
        self.assertEqual(names, {"Visible"})


class AuthThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.super_admin = User.objects.create_superuser("admin@example.com", "AdminPass123!", full_name="Admin")
        self.accountant = User.objects.create_user("acct@example.com", "AcctPass123!", full_name="Acct")

    def tearDown(self):
        cache.clear()

    def test_login_endpoint_is_scoped_throttled(self):
        payload = {"email": "acct@example.com", "password": "wrong-password"}

        responses = [self.client.post("/api/auth/login/", payload) for _ in range(21)]

        self.assertTrue(all(response.status_code == status.HTTP_400_BAD_REQUEST for response in responses[:20]))
        self.assertEqual(responses[-1].status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_token_refresh_endpoint_is_scoped_throttled(self):
        payload = {"refresh": "not-a-token"}
        responses = [self.client.post("/api/auth/refresh/", payload) for _ in range(61)]

        self.assertTrue(all(response.status_code == status.HTTP_401_UNAUTHORIZED for response in responses[:60]))
        self.assertEqual(responses[-1].status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_password_reset_endpoint_is_scoped_throttled(self):
        self.client.force_authenticate(self.super_admin)
        responses = [
            self.client.post(
                f"/api/accountants/{self.accountant.id}/reset-password/",
                {"password": f"NewStrongPass{index}!"},
            )
            for index in range(11)
        ]

        self.assertTrue(all(response.status_code == status.HTTP_200_OK for response in responses[:10]))
        self.assertEqual(responses[-1].status_code, status.HTTP_429_TOO_MANY_REQUESTS)
