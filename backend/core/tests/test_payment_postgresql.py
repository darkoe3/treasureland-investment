from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import threading
import unittest

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from core.models import (
    Agency,
    AuditAction,
    AuditLog,
    PaymentObligation,
    PayerPayment,
    PaymentPayer,
    User,
)


@unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL concurrency tests require PostgreSQL.")
class PaymentPostgreSQLConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="pg-payment-admin@example.com",
            password="PaymentPass123!",
            full_name="PG Payment Admin",
        )
        self.agency = Agency.objects.create(name="PG Agency", code="pg-agency")
        self.payer = PaymentPayer.objects.create(agency=self.agency, payer_name="PG Payer", created_by=self.admin)

    def add_obligation(self, amount="100.00", payer=None):
        return PaymentObligation.objects.create(
            agency=self.agency,
            payer=payer or self.payer,
            description="PostgreSQL concurrency obligation",
            obligation_date=date(2026, 9, 24),
            total_expected=Decimal(amount),
            created_by=self.admin,
        )

    def api_payment(self, obligation_id, amount, key, barrier):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            client = APIClient()
            client.force_authenticate(self.admin)
            response = client.post(
                "/api/payer-payments/",
                {
                    "obligation": obligation_id,
                    "amount_received": str(amount),
                    "payment_method": "CASH",
                    "idempotency_key": key,
                },
                format="json",
            )
            return response.status_code, getattr(response, "data", None)
        finally:
            connections["default"].close()

    def test_simultaneous_excess_payments_only_one_succeeds(self):
        obligation = self.add_obligation("100.00")
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: self.api_payment(obligation.id, "60.00", key, barrier), ("pg-excess-a", "pg-excess-b")))
        self.assertEqual(sorted(status for status, _ in results), [201, 400])
        self.assertEqual(PayerPayment.objects.filter(obligation=obligation, status=PayerPayment.PaymentStatus.POSTED).count(), 1)
        self.assertEqual(obligation.__class__.objects.get(pk=obligation.pk).total_paid, Decimal("60.00"))

    def test_simultaneous_valid_partials_both_succeed(self):
        obligation = self.add_obligation("100.00")
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: self.api_payment(obligation.id, "50.00", key, barrier), ("pg-partial-a", "pg-partial-b")))
        self.assertEqual(sorted(status for status, _ in results), [201, 201])
        self.assertEqual(PayerPayment.objects.filter(obligation=obligation, status=PayerPayment.PaymentStatus.POSTED).count(), 2)
        self.assertEqual(PaymentObligation.objects.get(pk=obligation.pk).total_paid, Decimal("100.00"))

    def test_simultaneous_receipt_allocation_is_unique(self):
        obligations = [self.add_obligation("10.00", PaymentPayer.objects.create(agency=self.agency, payer_name=f"Receipt Payer {index}", created_by=self.admin)) for index in range(2)]
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: self.api_payment(item.id, "10.00", f"pg-receipt-{item.id}", barrier), obligations))
        self.assertEqual([status for status, _ in results], [201, 201])
        self.assertEqual(PayerPayment.objects.values("receipt_number").distinct().count(), 2)

    def test_simultaneous_obligation_allocation_is_unique(self):
        barrier = threading.Barrier(2)

        def create_obligation(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return PaymentObligation.objects.create(
                    agency=self.agency,
                    payer=self.payer,
                    description=f"Concurrent obligation {index}",
                    obligation_date=date(2026, 9, 24),
                    total_expected=Decimal("10.00"),
                    created_by=self.admin,
                ).obligation_number
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            numbers = list(pool.map(create_obligation, (1, 2)))
        self.assertEqual(len(set(numbers)), 2)

    def test_identical_concurrent_idempotency_retries_create_one_payment(self):
        obligation = self.add_obligation("100.00")
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.api_payment(obligation.id, "40.00", "pg-same-key", barrier), (1, 2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 201])
        self.assertEqual(PayerPayment.objects.filter(idempotency_key="pg-same-key").count(), 1)

    def test_conflicting_concurrent_idempotency_reuse_is_rejected(self):
        obligation = self.add_obligation("100.00")
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda amount: self.api_payment(obligation.id, amount, "pg-conflict-key", barrier), ("40.00", "50.00")))
        self.assertEqual(sorted(status for status, _ in results), [201, 400])
        self.assertEqual(PayerPayment.objects.filter(idempotency_key="pg-conflict-key").count(), 1)

    def test_simultaneous_reversal_has_one_transition_and_audit_event(self):
        obligation = self.add_obligation("100.00")
        client = APIClient()
        client.force_authenticate(self.admin)
        created = client.post("/api/payer-payments/", {"obligation": obligation.id, "amount_received": "40.00", "payment_method": "CASH", "idempotency_key": "pg-reversal-key"}, format="json")
        payment_id = created.data["id"]
        barrier = threading.Barrier(2)

        def reverse_payment():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                reverse_client = APIClient()
                reverse_client.force_authenticate(self.admin)
                response = reverse_client.post(f"/api/payer-payments/{payment_id}/reverse/", {"reason": "Concurrent correction", "confirmed": True}, format="json")
                return response.status_code
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: reverse_payment(), (1, 2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(PayerPayment.objects.get(pk=payment_id).status, PayerPayment.PaymentStatus.REVERSED)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.PAYMENT_REVERSED).count(), 1)