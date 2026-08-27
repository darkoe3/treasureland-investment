from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Agency, Game, Person, TPMCode, UserAgencyAssignment, UserRole, WeeklyGameSchedule


User = get_user_model()


class ModelTests(TestCase):
    def test_email_based_user_creation(self):
        user = User.objects.create_user(
            email="Accountant@Example.com",
            password="test-pass-123",
            full_name="Accountant One",
        )

        self.assertEqual(user.email, "Accountant@example.com")
        self.assertTrue(user.check_password("test-pass-123"))
        self.assertEqual(user.role, UserRole.ACCOUNTANT)
        self.assertFalse(user.is_staff)

    def test_unique_agency_names_and_codes(self):
        Agency.objects.create(name="Musa 1", code="musa-1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Agency.objects.create(name="Musa 1", code="musa-one")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Agency.objects.create(name="Musa One", code="musa-1")

    def test_unique_tpm_codes_and_multiple_codes_for_person(self):
        agency = Agency.objects.create(name="Treasure Land", code="treasure-land")
        person = Person.objects.create(agency=agency, full_name="Jane Agent", agent_type="MAIN_AGENT")

        TPMCode.objects.create(person=person, code="TPM001")
        TPMCode.objects.create(person=person, code="TPM002")

        self.assertEqual(person.tpm_codes.count(), 2)
        with self.assertRaises(IntegrityError):
            TPMCode.objects.create(person=person, code="TPM001")

    def test_accountant_assignment_to_multiple_agencies_and_duplicate_prevention(self):
        accountant = User.objects.create_user("acct@example.com", "pass", full_name="Acct")
        agency_one = Agency.objects.create(name="Musa 1", code="musa-1")
        agency_two = Agency.objects.create(name="Musa 2", code="musa-2")

        UserAgencyAssignment.objects.create(user=accountant, agency=agency_one)
        UserAgencyAssignment.objects.create(user=accountant, agency=agency_two)

        self.assertEqual(accountant.agency_assignments.count(), 2)
        with self.assertRaises(ValidationError):
            UserAgencyAssignment.objects.create(user=accountant, agency=agency_one)

    def test_seed_command_is_idempotent(self):
        call_command("seed_initial_data")
        first_counts = (Agency.objects.count(), Game.objects.count(), WeeklyGameSchedule.objects.count())
        call_command("seed_initial_data")
        second_counts = (Agency.objects.count(), Game.objects.count(), WeeklyGameSchedule.objects.count())

        self.assertEqual(first_counts, second_counts)
        self.assertEqual(first_counts[0], 5)
        self.assertEqual(first_counts[2], 33)


class APIPermissionTests(APITestCase):
    def setUp(self):
        self.super_admin = User.objects.create_superuser(
            email="admin@example.com",
            password="admin-pass-123",
            full_name="Super Admin",
        )
        self.accountant = User.objects.create_user(
            email="accountant@example.com",
            password="acct-pass-123",
            full_name="Accountant",
        )
        self.agency_one = Agency.objects.create(name="Musa 1", code="musa-1")
        self.agency_two = Agency.objects.create(name="Sango", code="sango")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency_one)
        self.person = Person.objects.create(
            agency=self.agency_one,
            full_name="Assigned Person",
            agent_type="MAIN_AGENT",
        )
        self.other_person = Person.objects.create(
            agency=self.agency_two,
            full_name="Other Person",
            agent_type="SUBAGENT",
        )

    def test_unauthenticated_api_access_is_rejected(self):
        response = self.client.get("/api/agencies/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accountant_sees_only_assigned_agencies(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.get("/api/agencies/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {item["name"] for item in response.data["results"]} if "results" in response.data else {item["name"] for item in response.data}
        self.assertEqual(names, {"Musa 1"})

    def test_accountant_cannot_create_people_or_tpm_codes(self):
        self.client.force_authenticate(self.accountant)

        person_response = self.client.post(
            "/api/people/",
            {"agency": self.agency_one.id, "full_name": "Blocked Person", "agent_type": "MAIN_AGENT"},
        )
        tpm_response = self.client.post(
            "/api/tpm-codes/",
            {"person": self.person.id, "code": "TPM-BLOCKED"},
        )

        self.assertEqual(person_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(tpm_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_has_complete_access(self):
        self.client.force_authenticate(self.super_admin)

        agencies_response = self.client.get("/api/agencies/")
        person_response = self.client.post(
            "/api/people/",
            {"agency": self.agency_two.id, "full_name": "New Person", "agent_type": "SUBAGENT"},
        )
        tpm_response = self.client.post(
            "/api/tpm-codes/",
            {"person": self.person.id, "code": "TPM-SUPER"},
        )

        self.assertEqual(agencies_response.status_code, status.HTTP_200_OK)
        self.assertEqual(person_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(tpm_response.status_code, status.HTTP_201_CREATED)

        data = agencies_response.data["results"] if "results" in agencies_response.data else agencies_response.data
        self.assertEqual(len(data), 2)
