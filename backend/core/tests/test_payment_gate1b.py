from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import (
    Agency,
    AuditAction,
    AuditLog,
    PaymentObligation,
    PaymentPayer,
    PayerPayment,
    PayerSubAgentAssignment,
    Person,
    TPMCode,
    User,
    UserAgencyAssignment,
)


class PaymentGate1BApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="gate1b-admin@example.com",
            password="PaymentPass123!",
            full_name="Gate 1B Admin",
        )
        self.accountant = User.objects.create_user(
            email="gate1b-accountant@example.com",
            password="PaymentPass123!",
            full_name="Gate 1B Accountant",
        )
        self.agency = Agency.objects.create(name="Gate 1B Agency", code="gate1b-agency")
        self.other_agency = Agency.objects.create(name="Gate 1B Other", code="gate1b-other")
        UserAgencyAssignment.objects.create(
            user=self.accountant,
            agency=self.agency,
            can_create=True,
            can_edit=True,
            can_delete=True,
        )
        self.payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Gate Payer", created_by=self.admin)
        self.target_payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Target Payer", created_by=self.admin)
        self.obligation = PaymentObligation.objects.create(
            agency=self.agency,
            payer=self.payer,
            description="Gate obligation",
            obligation_date="2026-09-24",
            total_expected=Decimal("100.00"),
            created_by=self.admin,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def post_payment(self, amount, key, method="CASH", payment_date=None, obligation=None):
        payload = {
            "obligation": (obligation or self.obligation).id,
            "amount_received": str(amount),
            "payment_method": method,
            "payment_reference": "REF-1" if method != "CASH" else "",
            "idempotency_key": key,
        }
        if payment_date:
            payload["payment_date"] = payment_date
        return self.client.post("/api/payer-payments/", payload, format="json")

    def test_payer_reassignment_is_between_payers_and_audit_metadata_is_safe(self):
        person = Person.objects.create(agency=self.agency, full_name="Gate Person", agent_type="SUBAGENT")
        code = TPMCode.objects.create(person=person, code="GATE-SUB-1")
        assigned = self.client.post(
            f"/api/payment-payers/{self.payer.id}/assign_sub_agent/",
            {"sub_agent_number": code.id},
            format="json",
        )
        self.assertEqual(assigned.status_code, 200)
        reassigned = self.client.post(
            f"/api/payment-payers/{self.payer.id}/reassign_sub_agent/",
            {"sub_agent_number": code.id, "new_payer": self.target_payer.id, "confirmed": True},
            format="json",
        )
        self.assertEqual(reassigned.status_code, 200)
        self.assertFalse(PayerSubAgentAssignment.objects.get(payer=self.payer, sub_agent_number=code).is_active)
        self.assertTrue(PayerSubAgentAssignment.objects.get(payer=self.target_payer, sub_agent_number=code).is_active)
        audit = AuditLog.objects.get(action=AuditAction.PAYER_SUBAGENT_REASSIGNED)
        self.assertEqual(audit.new_values["new_payer_id"], self.target_payer.id)
        self.assertNotIn("reason", audit.new_values)
        self.assertNotIn("payer_name", audit.new_values)

    def test_filters_pagination_and_accountant_object_isolation(self):
        other_payer = PaymentPayer.objects.create(agency=self.other_agency, payer_name="Other Payer", created_by=self.admin)
        other_obligation = PaymentObligation.objects.create(
            agency=self.other_agency,
            payer=other_payer,
            description="Other obligation",
            obligation_date="2026-09-24",
            total_expected=Decimal("10.00"),
            created_by=self.admin,
        )
        other_payment = self.post_payment("10.00", "gate-other", obligation=other_obligation)
        self.assertEqual(other_payment.status_code, 201)
        second_payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Second Gate Payer", created_by=self.admin)
        PaymentObligation.objects.create(
            agency=self.agency,
            payer=second_payer,
            description="Second gate obligation",
            obligation_date="2026-09-24",
            total_expected=Decimal("20.00"),
            created_by=self.admin,
        )
        self.assertEqual(self.client.get("/api/payment-payers/?page_size=1").status_code, 200)
        payer_page = self.client.get("/api/payment-payers/?page_size=1").data
        self.assertEqual(len(payer_page["results"]), 1)
        self.assertEqual(self.client.get("/api/payment-obligations/?obligation_start=2026-09-25&obligation_end=2026-09-24").status_code, 400)
        self.assertEqual(self.client.get("/api/payer-payments/?payment_method=INVALID").status_code, 400)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(f"/api/payer-payments/{other_payment.data['id']}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/payment-obligations/?agency={self.other_agency.id}").status_code, 403)
        self.assertEqual(self.client.get(f"/api/payer-payments/?recorded_by={self.admin.id}").status_code, 403)

    def test_analytics_uses_payment_domain_filters_and_inclusive_dates(self):
        first = self.post_payment("40.00", "gate-analytics-one", payment_date="2026-09-24T10:00:00Z")
        second = self.post_payment("20.00", "gate-analytics-two", method="MOBILE_MONEY", payment_date="2026-09-25T10:00:00Z")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        PayerPayment.objects.filter(pk=first.data["id"]).update(payment_date="2026-09-24T10:00:00Z")
        PayerPayment.objects.filter(pk=second.data["id"]).update(payment_date="2026-09-25T10:00:00Z")
        self.client.post(
            f"/api/payer-payments/{first.data['id']}/reverse/",
            {"reason": "Correction", "confirmed": True},
            format="json",
        )
        analytics = self.client.get("/api/payments/analytics/?payment_start=2026-09-24&payment_end=2026-09-25")
        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(analytics.data["obligation_portfolio"]["total_expected"], "100.00")
        self.assertEqual(analytics.data["collections"]["gross_posted_amount"], "60.00")
        self.assertEqual(analytics.data["collections"]["reversed_amount"], "40.00")
        self.assertEqual(analytics.data["collections"]["posted_receipt_count"], 1)
        self.assertEqual(analytics.data["collections"]["reversed_receipt_count"], 1)
        self.assertEqual(analytics.data["trends"]["grouping"], "daily")
        self.assertEqual([period["period"] for period in analytics.data["trends"]["periods"]], ["2026-09-24", "2026-09-25"])
        self.assertEqual(analytics.data["collections"]["by_payment_method"]["MOBILE_MONEY"]["gross_posted_amount"], "20.00")

    def test_accountant_can_read_assigned_analytics_but_not_other_agency(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.get("/api/payments/analytics/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("agency_breakdown", response.data)
        self.assertEqual(self.client.get(f"/api/payments/analytics/?agency={self.other_agency.id}").status_code, 403)
