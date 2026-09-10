from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase

from core.models import AuditLog, TPMCode, UserAgencyAssignment
from core.serializers import TPMDailyTransactionSerializer
from core.tests.test_phase_4 import Phase4Mixin


class TPMReassignmentTests(Phase4Mixin, APITestCase):
    def setUp(self):
        self.setUpBase()
        self.client.force_authenticate(self.acct)
        self.url = f"/api/tpm-codes/{self.tpm_a.id}/"

    def reassign(self, person=None, **extra):
        return self.client.patch(self.url, {"person": (person or self.sub).id,
            "confirm_reassignment": True, **extra}, format="json")

    def test_duplicates_active_inactive_and_case_insensitive(self):
        count = TPMCode.objects.count()
        for active in (True, False):
            self.tpm_a.is_active = active
            self.tpm_a.save()
            for code in ("TPM-A", "tpm-a", " TPM-A "):
                response = self.client.post("/api/tpm-codes/", {"person": self.sub.id, "code": code})
                self.assertEqual(response.status_code, 400)
                self.assertIn("TPM code TPM-A already exists and is assigned to Ayo. Edit the existing TPM code instead.", str(response.data))
        self.assertEqual(TPMCode.objects.count(), count)

    def test_inactive_can_be_found_reassigned_and_reactivated(self):
        self.tpm_a.is_active = False
        self.tpm_a.save()
        response = self.client.get("/api/tpm-codes/?active=false&search=tpm-a")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.tpm_a.id, [row["id"] for row in response.data])
        people = self.client.get("/api/people/?search=tpm-a")
        self.assertIn(self.tpm_a.id, [code["id"] for person in people.data for code in person["tpm_codes"]])
        self.assertEqual(self.reassign(is_active=True).status_code, 200)
        self.tpm_a.refresh_from_db()
        self.assertEqual(self.tpm_a.person_id, self.sub.id)
        self.assertTrue(self.tpm_a.is_active)

    def test_active_requires_confirmation_and_logs_immutable_audit(self):
        response = self.client.patch(self.url, {"person": self.sub.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action="TPM_CODE_UPDATED").exists())
        self.assertEqual(self.reassign().status_code, 200)
        log = AuditLog.objects.get(action="TPM_CODE_UPDATED")
        self.assertEqual(log.object_id, str(self.tpm_a.id))
        self.assertEqual(log.old_values["person"], self.person.id)
        self.assertEqual(log.new_values["person"], self.sub.id)
        self.assertEqual(log.agency_id, self.musa.id)
        self.assertEqual(log.user_id, self.acct.id)
        self.assertIsNotNone(log.created_at)
        with self.assertRaises(ValidationError):
            log.save()
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(pk=log.pk).update(description="changed")
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(pk=log.pk).delete()

    def test_historical_snapshots_and_totals_unchanged(self):
        sheet = self.sheet()
        txn = self.txn(sheet, self.tpm_a)
        self.txn(sheet, self.tpm_b)
        url = f"/api/daily-sheets/{sheet.id}/summary/"
        before = self.client.get(url).data["person_totals"]
        old = (txn.person_name_snapshot, txn.agent_type_snapshot, txn.person_id_snapshot, txn.tpm_code_snapshot)
        self.assertEqual(self.reassign(code="RENAMED").status_code, 200)
        txn.refresh_from_db()
        txn.save()
        txn.refresh_from_db()
        self.assertEqual(old, (txn.person_name_snapshot, txn.agent_type_snapshot, txn.person_id_snapshot, txn.tpm_code_snapshot))
        self.assertEqual(self.client.get(url).data["person_totals"], before)
        self.assertEqual(TPMDailyTransactionSerializer(txn).data["tpm_code_value"], "TPM-A")
        self.assertEqual(TPMDailyTransactionSerializer(txn).data["person_total"], Decimal("285.00"))

    def test_both_agencies_require_edit_permission(self):
        self.assertEqual(self.reassign(self.other_person).status_code, 403)
        self.assignment.can_edit = False
        self.assignment.save()
        self.assertEqual(self.reassign().status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.reassign().status_code, 404)
        self.tpm_a.refresh_from_db()
        self.assertEqual(self.tpm_a.person_id, self.person.id)
        self.assertFalse(AuditLog.objects.filter(action="TPM_CODE_UPDATED").exists())

    def test_accountant_with_both_permissions_and_admin_can_cross_agency(self):
        UserAgencyAssignment.objects.create(user=self.acct, agency=self.sango, can_edit=True)
        self.assertEqual(self.reassign(self.other_person).status_code, 200)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.reassign(self.person).status_code, 200)

    def test_failed_audit_rolls_back_reassignment(self):
        with patch("core.views.log_audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.reassign(is_active=False)
        self.tpm_a.refresh_from_db()
        self.assertEqual(self.tpm_a.person_id, self.person.id)
        self.assertTrue(self.tpm_a.is_active)

    def test_destination_permission_alone_is_insufficient(self):
        UserAgencyAssignment.objects.create(user=self.acct, agency=self.sango, can_edit=True)
        self.assignment.can_edit = False
        self.assignment.save()
        self.assertEqual(self.reassign(self.other_person).status_code, 403)
