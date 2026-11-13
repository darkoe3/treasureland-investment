from decimal import Decimal
from unittest.mock import patch
from django.db import connection, connections, close_old_connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from core.models import (Agency, AuditLog, PaymentObligation, PaymentPayer, PayerPayment, PayerSubAgentAssignment, Person, TPMCode, TerminalNumber, User, UserAgencyAssignment)
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor


class PaymentNumberTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="number-admin@example.com", password="TestingPass123!", full_name="Recorder")
        self.accountant = User.objects.create_user(email="number-accountant@example.com", password="TestingPass123!", full_name="Accountant")
        self.agency = Agency.objects.create(name="Number agency", code="number-agency")
        self.other = Agency.objects.create(name="Other agency", code="number-other")
        self.permission = UserAgencyAssignment.objects.create(user=self.accountant, agency=self.agency, can_create=True, can_edit=True)
        self.payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Saved Payer", created_by=self.admin)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f"/api/agencies/{self.agency.pk}/payment-numbers/"

    def quick(self, code="SUB-001", terminal="TERM-001", **extra):
        return self.client.post(self.url, {"payer": self.payer.pk, "sub_agent_number": code, "terminal_number": terminal, "confirmed": True, **extra}, format="json")

    def obligation(self, number):
        from core.game_schedule import apply_approved_weekly_game_schedule
        from core.payment_games import effective_games
        apply_approved_weekly_game_schedule()
        game = effective_games("2026-11-03")[0]["game_id"]
        response = self.client.post("/api/payment-obligations/", {"agency": self.agency.pk, "payer": self.payer.pk, "sub_agent_number": number, "game": game, "business_date": "2026-11-03", "description": "Collection", "obligation_date": "2026-11-03", "total_expected": "100.00"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return PaymentObligation.objects.get(pk=response.data["id"])

    def pay(self, obligation, key="number-payment", amount="30.00"):
        response = self.client.post("/api/payer-payments/", {"obligation": obligation.pk, "amount_received": amount, "payment_method": "CASH", "idempotency_key": key}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return PayerPayment.objects.get(pk=response.data["id"])

    def test_quick_create_atomic_records_and_saved_payer_person(self):
        response = self.quick()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((TPMCode.objects.count(), TerminalNumber.objects.count(), PayerSubAgentAssignment.objects.count()), (1, 1, 1))
        self.payer.refresh_from_db()
        self.assertEqual(self.payer.register_person.full_name, self.payer.payer_name)
        self.assertEqual(self.quick("SUB-002", "TERM-002").status_code, 201)
        self.assertEqual(Person.objects.count(), 1)

    def test_search_code_terminal_and_payer_multiple_numbers(self):
        number = self.quick().data["id"]
        self.quick("SUB-002", "TERM-002")
        for search in ("sub-001", "term-001"):
            response = self.client.get(self.url, {"search": search})
            self.assertEqual([row["id"] for row in response.data["results"]], [number])
        self.assertEqual(self.client.get(self.url, {"search": "Saved Payer"}).data["count"], 2)
        self.assertEqual(self.client.get(self.url).data["count"], 0)

    def test_agency_scope_and_read_only_permissions(self):
        self.quick()
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(self.url, {"search": "SUB"}).status_code, 200)
        other_url = f"/api/agencies/{self.other.pk}/payment-numbers/"
        self.assertEqual(self.client.get(other_url, {"search": "SUB"}).status_code, 403)
        self.assertEqual(self.client.post(other_url, {}, format="json").status_code, 403)
        self.permission.can_edit = False
        self.permission.save()
        self.assertEqual(self.quick("SUB-003", "TERM-003").status_code, 403)
        self.assertEqual(self.client.get(self.url, {"search": "SUB"}).status_code, 200)

    def test_case_insensitive_duplicates_and_inactive_duplicates(self):
        self.quick()
        self.assertIn("already exists and is assigned to Saved Payer", str(self.quick("sub-001", "NEW-T").data))
        self.assertIn("already exists and is assigned to Sub-Agent Number SUB-001", str(self.quick("NEW-S", "term-001").data))
        TerminalNumber.objects.update(is_active=False)
        TPMCode.objects.update(is_active=False)
        self.assertEqual(self.quick("sub-001", "NEW-T").status_code, 400)
        self.assertEqual(self.quick("NEW-S", "term-001").status_code, 400)
        self.assertEqual(TPMCode.objects.count(), 1)

    def test_failure_rolls_back_person_number_and_assignment(self):
        from rest_framework.exceptions import ValidationError
        with patch("core.payment_numbers.TerminalNumber.objects.create", side_effect=ValidationError("Invalid terminal")):
            self.assertEqual(self.quick().status_code, 400)
        self.assertEqual(Person.objects.count(), 0)
        self.assertEqual(TPMCode.objects.count(), 0)
        self.payer.refresh_from_db()
        self.assertIsNone(self.payer.register_person_id)

    def test_cross_agency_payer_and_identifier_validation(self):
        other_payer = PaymentPayer.objects.create(agency=self.other, payer_name="Other payer", created_by=self.admin)
        self.assertEqual(self.quick(payer=other_payer.pk).status_code, 404)
        for code in ("", " ", "has space", "<script>", "x" * 81):
            self.assertEqual(self.quick(code=code).status_code, 400)
        self.assertEqual(self.quick(confirmed=False).status_code, 400)
        self.assertFalse(TPMCode.objects.exists())

    def test_inactive_agency_payer_number_and_terminal_selection(self):
        number = self.quick().data["id"]
        for model in (TerminalNumber, TPMCode, PaymentPayer, Agency):
            obj = model.objects.first()
            model.objects.filter(pk=obj.pk).update(is_active=False)
            if model == Agency:
                self.assertEqual(self.quick("NEW", "NEW-T").status_code, 400)
            else:
                response = self.client.get(self.url, {"search": "SUB-001"})
                self.assertFalse(response.data["results"][0]["selectable"])
            response = self.client.post("/api/payment-obligations/", {"agency": self.agency.pk, "payer": self.payer.pk, "sub_agent_number": number, "description": "Inactive", "obligation_date": "2026-11-03", "total_expected": "100"}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            model.objects.filter(pk=obj.pk).update(is_active=True)

    def test_new_obligation_requires_explicit_number_and_wrong_payer_rejected(self):
        payload = {"agency": self.agency.pk, "payer": self.payer.pk, "description": "Missing number", "obligation_date": "2026-11-03", "total_expected": "100"}
        self.assertEqual(self.client.post("/api/payment-obligations/", payload, format="json").status_code, 400)
        payload["sub_agent_number"] = self.quick().data["id"]
        other = PaymentPayer.objects.create(agency=self.agency, payer_name="Different payer", created_by=self.admin)
        payload["payer"] = other.pk
        self.assertEqual(self.client.post("/api/payment-obligations/", payload, format="json").status_code, 400)

    def test_legacy_remains_payable_receiptable_and_reversible(self):
        legacy = PaymentObligation.objects.create(agency=self.agency, payer=self.payer, description="Legacy", obligation_date="2026-11-03", total_expected=100, created_by=self.admin)
        payment = self.pay(legacy)
        self.assertEqual(payment.sub_agent_number_snapshot, "")
        receipt = self.client.get(f"/api/payer-payments/{payment.pk}/receipt/")
        self.assertEqual(receipt.status_code, 200)
        self.assertIn(b"legacy obligation", receipt.content)
        response = self.client.post(f"/api/payer-payments/{payment.pk}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        legacy.refresh_from_db()
        self.assertEqual(legacy.balance, Decimal("100.00"))

    def test_snapshots_survive_reassignment_and_rename_and_cannot_be_edited(self):
        number = self.quick().data["id"]
        obligation = self.obligation(number)
        payment = self.pay(obligation)
        target = PaymentPayer.objects.create(agency=self.agency, payer_name="New owner", created_by=self.admin)
        response = self.client.post(f"/api/payment-payers/{self.payer.pk}/reassign_sub_agent/", {"sub_agent_number": number, "new_payer": target.pk, "confirmed": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        PaymentPayer.objects.filter(pk=self.payer.pk).update(payer_name="Renamed")
        Agency.objects.filter(pk=self.agency.pk).update(name="Renamed agency")
        later = self.pay(obligation, key="after-reassignment")
        for record in (obligation, payment, later):
            record.refresh_from_db()
            self.assertEqual(record.sub_agent_number_snapshot, "SUB-001")
            self.assertEqual(record.terminal_number_snapshot, "TERM-001")
            self.assertEqual(record.payer_name_snapshot, "Saved Payer")
            self.assertEqual(record.payer_id_snapshot, self.payer.pk)
            self.assertEqual(record.agency_id_snapshot, self.agency.pk)
        from django.core.exceptions import ValidationError
        obligation.sub_agent_number_snapshot = "Different"
        with self.assertRaises(ValidationError):
            obligation.save()
        payment.terminal_number_snapshot = "Different"
        with self.assertRaises(ValidationError):
            payment.save()

    def test_number_analytics_filters_reversals_and_payer_aggregate(self):
        first = self.obligation(self.quick().data["id"])
        second = self.obligation(self.quick("SUB-002", "TERM-002").data["id"])
        payment = self.pay(first)
        self.pay(first, "second-posting", "20.00")
        self.pay(second, "other-number", "40.00")
        self.client.post(f"/api/payer-payments/{payment.pk}/reverse/", {"confirmed": True, "reason": "Correction"}, format="json")
        result = self.client.get("/api/payments/analytics/", {"payer": self.payer.pk}).data
        self.assertEqual(result["obligation_portfolio"]["total_expected"], "200.00")
        self.assertEqual(result["collections"]["net_collected_amount"], "60.00")
        rows = result["number_breakdown"]["results"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["gross_posted_amount"], "50.00")
        self.assertEqual(rows[0]["reversed_amount"], "30.00")
        self.assertEqual(rows[0]["outstanding_balance"], "80.00")
        self.assertEqual(rows[0]["payment_count"], 2)
        self.assertEqual(self.client.get("/api/payment-obligations/", {"terminal_number": "TERM-002"}).data["count"], 1)
        self.assertEqual(self.client.get("/api/payer-payments/", {"sub_agent_number": first.sub_agent_number_id}).data["count"], 2)
        self.assertEqual(self.client.get(f"/api/payment-payers/{self.payer.pk}/numbers/").data["count"], 2)

    def test_audit_metadata_ids_only_and_immutable(self):
        self.obligation(self.quick().data["id"])
        events = AuditLog.objects.filter(action__in=["PAYMENT_NUMBER_CREATED", "PAYMENT_TERMINAL_CREATED", "PAYMENT_OBLIGATION_CREATED"])
        self.assertEqual(events.count(), 3)
        for event in events:
            self.assertTrue(all(key.endswith("_id") or key in {"source", "business_date", "timestamp"} for key in event.new_values))
            self.assertNotIn("Saved Payer", str(event.new_values))
            self.assertNotIn("SUB-001", str(event.new_values))
            self.assertEqual(event.new_values["actor_id"], self.admin.pk)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            events.update(description="changed")

    def test_number_link_cannot_be_changed_even_before_payment(self):
        first = self.quick().data["id"]
        second = self.quick("SUB-002", "TERM-002").data["id"]
        obligation = self.obligation(first)
        response = self.client.patch(f"/api/payment-obligations/{obligation.pk}/", {"sub_agent_number": second}, format="json")
        self.assertEqual(response.status_code, 400)
        other = PaymentPayer.objects.create(agency=self.agency, payer_name="Other owner", created_by=self.admin)
        response = self.client.patch(f"/api/payment-obligations/{obligation.pk}/", {"payer": other.pk}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_scoped_search_never_returns_other_agency_or_inactive_terminal_replacement(self):
        number = self.quick().data["id"]
        terminal = TerminalNumber.objects.get(sub_agent_number_id=number)
        terminal.is_active = False
        terminal.save()
        TerminalNumber.objects.create(terminal_number="NEW-TERMINAL", sub_agent_number_id=number, person=terminal.person, agency=self.agency, created_by=self.admin, updated_by=self.admin)
        response = self.client.get(self.url, {"search": "TERM-001"})
        self.assertFalse(response.data["results"][0]["selectable"])
        other_url = f"/api/agencies/{self.other.pk}/payment-numbers/"
        self.assertEqual(self.client.get(other_url, {"search": "SUB-001"}).data["count"], 0)

    def test_number_without_terminal_is_eligible_and_has_empty_snapshot(self):
        number = self.quick().data["id"]
        TerminalNumber.objects.filter(sub_agent_number_id=number).delete()
        row = self.client.get(self.url, {"search": "SUB-001"}).data["results"][0]
        self.assertTrue(row["selectable"])
        self.assertEqual(row["terminal_number"], "")
        self.assertEqual(self.obligation(number).terminal_number_snapshot, "")

    def test_analytics_filter_method_date_recorder_and_number_keeps_portfolio_distinct(self):
        obligation = self.obligation(self.quick().data["id"])
        self.pay(obligation)
        response = self.client.get("/api/payments/analytics/", {"agency": self.agency.pk, "sub_agent_number": obligation.sub_agent_number_id, "payment_method": "BANK_TRANSFER", "recorded_by": self.admin.pk, "payment_start": "2026-01-01", "payment_end": "2026-12-31"})
        row = response.data["number_breakdown"]["results"][0]
        self.assertEqual(row["total_expected"], "100.00")
        self.assertEqual(row["net_collected_amount"], "0.00")
        self.assertEqual(row["outstanding_balance"], "70.00")

    def test_reversed_payment_snapshots_stay_immutable(self):
        payment = self.pay(self.obligation(self.quick().data["id"]))
        self.client.post(f"/api/payer-payments/{payment.pk}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        payment.refresh_from_db()
        payment.terminal_number_snapshot = "Changed"
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            payment.save()


@unittest.skipUnless(connection.vendor == "postgresql", "Requires approved local PostgreSQL; never simulated using SQLite.")
class PaymentNumberConcurrencyTests(TransactionTestCase):
    def test_simultaneous_duplicate_creates_only_one_assignment(self):
        user = User.objects.create_superuser(email="concurrent-numbers@example.com", password="TestingPass123!", full_name="Recorder")
        agency = Agency.objects.create(name="Concurrent agency", code="concurrent-agency")
        payer = PaymentPayer.objects.create(agency=agency, payer_name="Payer", created_by=user)
        barrier = threading.Barrier(2)
        def create():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                return client.post(f"/api/agencies/{agency.pk}/payment-numbers/", {"payer": payer.pk, "sub_agent_number": "CON-001", "terminal_number": "CON-T-001", "confirmed": True}, format="json").status_code
            finally:
                connections["default"].close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create) for _ in range(2)]
            statuses = sorted(future.result(timeout=30) for future in futures)
        self.assertEqual(statuses, [201, 400])
        self.assertEqual(TPMCode.objects.count(), 1)
        self.assertEqual(TerminalNumber.objects.count(), 1)
        self.assertEqual(PayerSubAgentAssignment.objects.count(), 1)
