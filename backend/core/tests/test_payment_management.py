from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from unittest.mock import patch
from rest_framework.test import APIClient

from core.models import Agency, PaymentObligation, PayerPayment, PaymentPayer, User, UserAgencyAssignment, UserRole


class PaymentManagementModelTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="payments-admin@example.com",
            password="PaymentPass123!",
            full_name="Payments Admin",
        )
        self.agency = Agency.objects.create(name="Musa Agency", code="musa-agency")

    def test_payer_name_is_unique_within_agency_case_insensitive(self):
        PaymentPayer.objects.create(
            agency=self.agency,
            payer_name="Ama Mensah",
            created_by=self.admin,
        )

        with self.assertRaises(ValidationError):
            PaymentPayer.objects.create(
                agency=self.agency,
                payer_name="ama mensah",
                created_by=self.admin,
            )

    def test_obligation_tracks_paid_balance_and_status(self):
        payer = PaymentPayer.objects.create(
            agency=self.agency,
            payer_name="Benedicta",
            created_by=self.admin,
        )
        obligation = PaymentObligation.objects.create(
            agency=self.agency,
            payer=payer,
            description="September collection",
            obligation_date="2026-09-01",
            total_expected=Decimal("2000.00"),
            created_by=self.admin,
        )

        self.assertEqual(obligation.total_paid, Decimal("0.00"))
        self.assertEqual(obligation.balance, Decimal("2000.00"))
        self.assertEqual(obligation.status, PaymentObligation.ObligationStatus.OPEN)

        obligation.total_expected = Decimal("2500.00")
        obligation.full_clean()
        obligation.save(update_fields=["total_expected", "updated_at"])
        self.assertEqual(obligation.total_expected, Decimal("2500.00"))

        payment = PayerPayment.objects.create(
            obligation=obligation,
            receipt_number="TLI-PAY-2026-000001",
            agency_snapshot=self.agency.name,
            payer_name_snapshot=payer.payer_name,
            linked_sub_agent_numbers_snapshot=[],
            obligation_number_snapshot=obligation.obligation_number,
            obligation_description_snapshot=obligation.description,
            obligation_date_snapshot=obligation.obligation_date,
            expected_amount_snapshot=obligation.total_expected,
            amount_previously_paid=Decimal("0.00"),
            amount_received=Decimal("1000.00"),
            cumulative_amount_paid=Decimal("1000.00"),
            balance_after_payment=Decimal("1500.00"),
            payment_method="CASH",
            payment_reference="",
            recorded_by=self.admin,
            status="POSTED",
            idempotency_key="pay-immutable-1",
        )
        obligation.refresh_from_db()
        self.assertEqual(obligation.total_paid, Decimal("1000.00"))
        obligation.total_expected = Decimal("2600.00")
        with self.assertRaises(ValidationError):
            obligation.full_clean()

    def test_obligation_financial_fields_change_before_first_posted_payment(self):
        payer = PaymentPayer.objects.create(
            agency=self.agency,
            payer_name="Kofi",
            created_by=self.admin,
        )
        obligation = PaymentObligation.objects.create(
            agency=self.agency,
            payer=payer,
            description="October recovery",
            obligation_date="2026-10-01",
            total_expected=Decimal("1200.00"),
            created_by=self.admin,
        )

        new_payer = PaymentPayer.objects.create(
            agency=self.agency,
            payer_name="Adjoa",
            created_by=self.admin,
        )
        obligation.payer = new_payer
        obligation.total_expected = Decimal("1350.00")
        obligation.full_clean()
        obligation.save(update_fields=["payer", "total_expected", "updated_at"])

        obligation.refresh_from_db()
        self.assertEqual(obligation.payer_id, new_payer.id)
        self.assertEqual(obligation.total_expected, Decimal("1350.00"))

    def test_database_constraints_reject_invalid_payment_amount_and_reversal_metadata(self):
        payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Constraint Payer", created_by=self.admin)
        obligation = PaymentObligation.objects.create(
            agency=self.agency,
            payer=payer,
            description="Constraint obligation",
            obligation_date="2026-09-01",
            total_expected=Decimal("100.00"),
            created_by=self.admin,
        )
        payment = PayerPayment.objects.create(
            obligation=obligation,
            agency_snapshot=self.agency.name,
            payer_name_snapshot=payer.payer_name,
            obligation_number_snapshot=obligation.obligation_number,
            obligation_description_snapshot=obligation.description,
            obligation_date_snapshot=obligation.obligation_date,
            expected_amount_snapshot=obligation.total_expected,
            amount_previously_paid=Decimal("0.00"),
            amount_received=Decimal("10.00"),
            cumulative_amount_paid=Decimal("10.00"),
            balance_after_payment=Decimal("90.00"),
            payment_method="CASH",
            recorded_by=self.admin,
            idempotency_key="constraint-payment",
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                PayerPayment.objects.filter(pk=payment.pk).update(amount_received=Decimal("0.00"))
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                PayerPayment.objects.filter(pk=payment.pk).update(status=PayerPayment.PaymentStatus.REVERSED)


class PaymentManagementApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="payment-api-admin@example.com",
            password="PaymentPass123!",
            full_name="Payment API Admin",
        )
        self.accountant = User.objects.create_user(
            email="payment-api-accountant@example.com",
            password="PaymentPass123!",
            full_name="Payment Accountant",
        )
        self.other_agency = Agency.objects.create(name="Other Agency", code="other-agency")
        self.agency = Agency.objects.create(name="API Agency", code="api-agency")
        UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True, can_edit=True, can_delete=True)
        self.payer = PaymentPayer.objects.create(agency=self.agency, payer_name="API Payer", created_by=self.admin)
        self.obligation = PaymentObligation.objects.create(
            agency=self.agency,
            payer=self.payer,
            description="API obligation",
            obligation_date="2026-09-24",
            total_expected=Decimal("100.00"),
            created_by=self.admin,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def post_payment(self, amount="40.00", key="api-payment-1", method="CASH", reference="", obligation=None, notes=""):
        return self.client.post("/api/payer-payments/", {
            "obligation": (obligation or self.obligation).id,
            "amount_received": amount,
            "payment_method": method,
            "payment_reference": reference,
            "notes": notes,
            "idempotency_key": key,
        }, format="json")

    def test_partial_multiple_and_exact_final_payment(self):
        first = self.post_payment()
        second = self.post_payment("30.00", "api-payment-2")
        final = self.post_payment("30.00", "api-payment-3")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(final.status_code, 201)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, PaymentObligation.ObligationStatus.PAID)
        self.assertEqual(self.obligation.total_paid, Decimal("100.00"))

    def test_payment_rejects_missing_zero_negative_and_excess_amounts(self):
        self.assertEqual(self.post_payment("0.00", "zero").status_code, 400)
        self.assertEqual(self.post_payment("-1.00", "negative").status_code, 400)
        self.assertEqual(self.post_payment("101.00", "excess").status_code, 400)
        self.assertEqual(self.post_payment("10.00", "missing-key").status_code, 201)

    def test_cash_and_non_cash_reference_rules(self):
        self.assertEqual(self.post_payment("10.00", "cash-reference", reference="optional").status_code, 201)
        self.assertEqual(self.post_payment("10.00", "mobile-missing", method="MOBILE_MONEY").status_code, 400)
        self.assertEqual(self.post_payment("10.00", "mobile-valid", method="MOBILE_MONEY", reference="MM-1").status_code, 201)

    def test_idempotent_retry_and_conflicting_reuse(self):
        first = self.post_payment("20.00", "same-key")
        retry = self.post_payment("20.00", "same-key")
        conflict = self.post_payment("21.00", "same-key")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.data["id"], retry.data["id"])
        self.assertEqual(PayerPayment.objects.count(), 1)
        self.assertEqual(conflict.status_code, 400)

    def test_idempotency_key_is_required(self):
        response = self.client.post("/api/payer-payments/", {"obligation": self.obligation.id, "amount_received": "10.00", "payment_method": "CASH"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("idempotency_key", response.data)

    def test_posted_payment_cannot_update_or_delete(self):
        response = self.post_payment()
        payment = PayerPayment.objects.get(pk=response.data["id"])
        self.assertEqual(self.client.patch(f"/api/payer-payments/{payment.id}/", {"notes": "changed"}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/payer-payments/{payment.id}/").status_code, 400)

    def test_only_super_admin_can_reverse_and_reversal_recalculates(self):
        response = self.post_payment()
        payment = PayerPayment.objects.get(pk=response.data["id"])
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.post(f"/api/payer-payments/{payment.id}/reverse/", {"reason": "Not valid", "confirmed": True}, format="json").status_code, 403)
        self.client.force_authenticate(self.admin)
        reversed_response = self.client.post(f"/api/payer-payments/{payment.id}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        self.assertEqual(reversed_response.status_code, 200)
        payment.refresh_from_db()
        self.obligation.refresh_from_db()
        self.assertEqual(payment.status, PayerPayment.PaymentStatus.REVERSED)
        self.assertEqual(self.obligation.status, PaymentObligation.ObligationStatus.OPEN)
        self.assertEqual(self.obligation.total_paid, Decimal("0.00"))

    def test_reversal_requires_reason_and_cannot_change_receipt(self):
        response = self.post_payment()
        payment = PayerPayment.objects.get(pk=response.data["id"])
        original_receipt = payment.receipt_number
        missing_reason = self.client.post(f"/api/payer-payments/{payment.id}/reverse/", {"confirmed": True}, format="json")
        self.assertEqual(missing_reason.status_code, 400)
        reversed_response = self.client.post(f"/api/payer-payments/{payment.id}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        self.assertEqual(reversed_response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.receipt_number, original_receipt)

    def test_obligation_cancellation_rules(self):
        response = self.post_payment()
        blocked = self.client.post(f"/api/payment-obligations/{self.obligation.id}/cancel/", {"reason": "Close"}, format="json")
        self.assertEqual(blocked.status_code, 400)
        payment = PayerPayment.objects.get(pk=response.data["id"])
        self.client.post(f"/api/payer-payments/{payment.id}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        cancelled = self.client.post(f"/api/payment-obligations/{self.obligation.id}/cancel/", {"reason": "Close"}, format="json")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self.post_payment("1.00", "cancelled-payment").status_code, 400)

    def test_stored_snapshots_survive_payer_and_agency_rename(self):
        response = self.post_payment()
        payment = PayerPayment.objects.get(pk=response.data["id"])
        self.payer.payer_name = "Renamed Payer"
        self.payer.save()
        self.agency.name = "Renamed Agency"
        self.agency.save()
        payment.refresh_from_db()
        self.assertEqual(payment.payer_name_snapshot, "API Payer")
        self.assertEqual(payment.agency_snapshot, "API Agency")

    def test_receipt_pdf_headers_content_and_reversed_status(self):
        response = self.post_payment()
        payment = PayerPayment.objects.get(pk=response.data["id"])
        receipt = self.client.get(f"/api/payer-payments/{payment.id}/receipt/")
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt["Content-Type"], "application/pdf")
        self.assertIn(f"{payment.receipt_number}.pdf", receipt["Content-Disposition"])
        self.assertTrue(receipt.content.startswith(b"%PDF"))
        self.client.post(f"/api/payer-payments/{payment.id}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        reversed_receipt = self.client.get(f"/api/payer-payments/{payment.id}/receipt/")
        self.assertEqual(reversed_receipt.status_code, 200)
        self.assertIn(b"REVERSED", reversed_receipt.content)

    def test_accountant_receipt_access_is_limited_to_assigned_agencies(self):
        response = self.post_payment()
        payment = PayerPayment.objects.get(pk=response.data["id"])
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(f"/api/payer-payments/{payment.id}/receipt/").status_code, 200)
        other_payer = PaymentPayer.objects.create(agency=self.other_agency, payer_name="Other Payer", created_by=self.admin)
        other_obligation = PaymentObligation.objects.create(agency=self.other_agency, payer=other_payer, description="Other", obligation_date="2026-09-24", total_expected=Decimal("10.00"), created_by=self.admin)
        self.client.force_authenticate(self.admin)
        other_payment_response = self.post_payment("10.00", "other-payment", obligation=other_obligation)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(f"/api/payer-payments/{other_payment_response.data['id']}/receipt/").status_code, 404)

    def test_payment_transaction_rolls_back_when_audit_fails(self):
        with patch("core.views.log_audit", side_effect=RuntimeError("forced test failure")):
            with self.assertRaises(RuntimeError):
                self.post_payment("10.00", "rollback-key")
        self.assertFalse(PayerPayment.objects.filter(idempotency_key="rollback-key").exists())
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.total_paid, Decimal("0.00"))

    def test_obligation_and_receipt_numbers_are_formatted_and_unique(self):
        second_payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Second Payer", created_by=self.admin)
        second_obligation = PaymentObligation.objects.create(agency=self.agency, payer=second_payer, description="Second", obligation_date="2026-09-24", total_expected=Decimal("10.00"), created_by=self.admin)
        first_payment = self.post_payment("10.00", "number-one")
        second_payment = self.post_payment("10.00", "number-two", obligation=second_obligation)
        self.assertRegex(self.obligation.obligation_number, r"^TLI-OBL-2026-\d{6}$")
        self.assertRegex(second_obligation.obligation_number, r"^TLI-OBL-2026-\d{6}$")
        self.assertNotEqual(self.obligation.obligation_number, second_obligation.obligation_number)
        self.assertRegex(first_payment.data["receipt_number"], r"^TLI-PAY-2026-\d{6}$")
        self.assertNotEqual(first_payment.data["receipt_number"], second_payment.data["receipt_number"])
