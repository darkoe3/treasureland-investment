from copy import copy, deepcopy
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch
from django.db import connection, connections, close_old_connections, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from core.game_schedule import apply_approved_weekly_game_schedule
from core.payment_games import effective_games
from core.models import (Agency, User, UserAgencyAssignment, PaymentPayer, Person, TPMCode,
    PayerSubAgentAssignment, PaymentObligation, PayerPayment, Game, HolidayGameOverride, AuditLog)


class GameFixture:
    def setUp(self):
        apply_approved_weekly_game_schedule()
        self.admin = User.objects.create_superuser(email="game-pay@example.com", password="Testpass123!", full_name="Recorder")
        self.agency = Agency.objects.create(name="Game agency", code="game-agency")
        self.payer = PaymentPayer.objects.create(agency=self.agency, payer_name="Game payer", created_by=self.admin)
        self.person = Person.objects.create(agency=self.agency, full_name="Number owner")
        self.number = TPMCode.objects.create(person=self.person, code="GAME-1")
        PayerSubAgentAssignment.objects.create(payer=self.payer, sub_agent_number=self.number, assigned_by=self.admin)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f"/api/agencies/{self.agency.pk}/payment-effective-games/"
        self.payload = {"agency": self.agency.pk, "payer": self.payer.pk, "sub_agent_number": self.number.pk,
            "business_date": "2026-11-09", "game": effective_games("2026-11-09")[0]["game_id"],
            "obligation_date": "2026-11-09", "description": "Game collection", "total_expected": "100.00"}

    def create(self, **changes):
        return self.client.post("/api/payment-obligations/", {**self.payload, **changes}, format="json")

    def pay(self, obligation, key, **changes):
        return self.client.post("/api/payer-payments/", {"obligation": obligation, "amount_received": "25.00", "payment_method": "CASH", "idempotency_key": key, **changes}, format="json")


class PaymentGameTests(GameFixture, TestCase):
    def test_weekdays_and_strict_endpoint(self):
        for day in range(7):
            business = date(2026, 11, 9) + timedelta(days=day)
            response = self.client.get(self.url, {"business_date": business.isoformat()})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data), 6 if day == 6 else 7)
            self.assertEqual(sum(row["category"] == "GHANA" for row in response.data), 1)
            self.assertEqual(sum(row["category"] == "DOUBLE_CHANCE" for row in response.data), 1)
        for query in ("", "?business_date=20261109", "?business_date=2026-02-30", "?business_date=2026-11-09&business_date=2026-11-10", "?business_date=2026-11-09&extra=1"):
            self.assertEqual(self.client.get(self.url + query).status_code, 400)
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url, {"business_date": "2026-11-09"}).status_code, 401)

    def test_schedule_configuration_errors_are_reported_by_effective_games_endpoint(self):
        from django.core.exceptions import ValidationError
        with patch("core.payment_games.effective_schedule_for_date", side_effect=ValidationError({"schedule": ["Invalid active schedule."]})):
            response = self.client.get(self.url, {"business_date": "2026-11-09"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid active schedule.", str(response.data))

    def test_explicit_valid_active_game_and_number_required(self):
        for changes in ({"game": None}, {"business_date": None}, {"game": Game.objects.get(name="Bonanza").pk}, {"sub_agent_number": None}, {"business_date": "2026-02-30"}):
            self.assertEqual(self.create(**changes).status_code, 400)
        Game.objects.filter(pk=self.payload["game"]).update(is_active=False)
        self.assertEqual(self.create().status_code, 400)
        self.assertEqual(PaymentObligation.objects.count(), 0)

    def test_permissions_and_relationships(self):
        accountant = User.objects.create_user(email="game-accountant@example.com", password="Testpass123!")
        assignment = UserAgencyAssignment.objects.create(user=accountant, agency=self.agency)
        other = Agency.objects.create(name="Other", code="other-game")
        self.client.force_authenticate(accountant)
        self.assertEqual(self.client.get(self.url, {"business_date": "2026-11-09"}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/agencies/{other.pk}/payment-effective-games/", {"business_date": "2026-11-09"}).status_code, 403)
        self.assertEqual(self.create().status_code, 403)
        assignment.can_create = True
        assignment.save()
        self.assertEqual(self.create(agency=other.pk).status_code, 400)
        self.assertEqual(self.create().status_code, 201)
        assignment.can_create = False
        assignment.save()
        self.assertEqual(self.pay(PaymentObligation.objects.get().pk, "denied").status_code, 403)
        self.assertEqual(self.client.get("/api/payment-obligations/", {"agency": other.pk, "game": self.payload["game"]}).status_code, 403)

    def test_snapshot_partial_payments_receipts_analytics_and_reversals(self):
        created = self.create()
        self.assertEqual(created.status_code, 201, created.data)
        obligation = PaymentObligation.objects.get()
        snapshot = deepcopy(obligation.game_snapshot)
        first = self.pay(obligation.pk, "first")
        second = self.pay(obligation.pk, "second")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.data["game_snapshot"], snapshot)
        self.assertEqual(self.pay(obligation.pk, "fabricated", game=999).status_code, 400)
        Game.objects.filter(pk=obligation.game_id).update(name="Renamed game")
        obligation.refresh_from_db()
        self.assertEqual(obligation.game_snapshot, snapshot)
        receipt = self.client.get(f"/api/payer-payments/{first.data['id']}/receipt/")
        self.assertEqual(receipt.status_code, 200)
        self.assertIn(snapshot["name"].encode(), receipt.content)
        self.assertIn(b"2026-11-09", receipt.content)
        self.assertEqual(self.client.patch(f"/api/payment-obligations/{obligation.pk}/", {"business_date": "2026-11-10"}, format="json").status_code, 400)
        self.client.post(f"/api/payer-payments/{first.data['id']}/reverse/", {"reason": "Correction", "confirmed": True}, format="json")
        result = self.client.get("/api/payments/analytics/", {"game": obligation.game_id}).data["game_breakdown"]["results"][0]
        self.assertEqual((result["total_expected"], result["gross_posted_amount"], result["reversed_amount"], result["net_collected_amount"], result["outstanding_balance"]), ("100.00", "50.00", "25.00", "25.00", "75.00"))
        self.assertEqual((result["obligation_count"], result["payment_count"]), (1, 2))
        self.assertIsNotNone(result["last_payment_date"])
        for grouping in ("game", "category", "business_date", "weekday", "agency", "payer", "sub_agent_number", "terminal_number"):
            self.assertEqual(self.client.get("/api/payments/analytics/", {"group_by": grouping}).status_code, 200)
        self.assertEqual(self.client.get("/api/payer-payments/", {"game_name": snapshot["name"]}).data["count"], 2)
        audit = AuditLog.objects.get(action="PAYMENT_OBLIGATION_CREATED")
        self.assertEqual(audit.new_values["game_id"], obligation.game_id)
        self.assertNotIn("description", audit.new_values)

    def test_duplicate_and_request_idempotency_and_cancelled_policy(self):
        first = self.create(creation_key="request-one")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.create(creation_key="request-one").status_code, 201)
        self.assertEqual(self.create(creation_key="request-one", total_expected="150.00").status_code, 400)
        duplicate = self.create()
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("Open the existing obligation", str(duplicate.data))
        self.assertEqual(PaymentObligation.objects.count(), 1)
        cancelled = self.client.post(f"/api/payment-obligations/{first.data['id']}/cancel/", {"reason": "Cancelled explicitly"}, format="json")
        self.assertEqual(cancelled.status_code, 200)
        replacement = self.create()
        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertNotEqual(replacement.data["obligation_number"], first.data["obligation_number"])
        self.assertEqual(self.create().status_code, 400)
        analytics = self.client.get("/api/payments/analytics/").data
        self.assertEqual(analytics["obligation_portfolio"]["total_expected"], "100.00")
        self.assertEqual(analytics["obligation_portfolio"]["status_counts"]["CANCELLED"], 1)
        audit = AuditLog.objects.get(action="PAYMENT_OBLIGATION_CANCELLED")
        self.assertEqual(audit.new_values["reason"], "Cancelled explicitly")

    def test_holiday_replaces_only_ghana_and_history_survives_change(self):
        normal = Game.objects.get(name="MSP")
        replacement = Game.objects.get(name="Bonanza")
        with patch("core.models.timezone.localdate", return_value=date(2026, 11, 7)):
            override = HolidayGameOverride.objects.create(holiday_date=date(2026, 11, 9), holiday_name="Test holiday", normal_game=normal, replacement_game=replacement, source_date=date(2026, 11, 6), created_by=self.admin)
        games = effective_games("2026-11-09")
        self.assertEqual(len(games), 7)
        self.assertNotIn(normal.pk, [row["game_id"] for row in games])
        self.assertEqual(sum(row["category"] == "TIMED" for row in games), 5)
        self.assertEqual(sum(row["category"] == "DOUBLE_CHANCE" for row in games), 1)
        self.assertEqual(self.create(game=normal.pk).status_code, 400)
        created = self.create(game=replacement.pk)
        self.assertEqual(created.status_code, 201, created.data)
        snapshot = created.data["game_snapshot"]
        self.assertTrue(snapshot["holiday_override_applied"])
        HolidayGameOverride.objects.filter(pk=override.pk).update(is_active=False)
        payment = self.pay(created.data["id"], "holiday")
        self.assertEqual(payment.data["game_snapshot"], snapshot)
        self.assertIn(b"Test holiday", self.client.get(f"/api/payer-payments/{payment.data['id']}/receipt/").content)

    def test_game_pagination_is_independent_of_number_pagination(self):
        for index in range(21):
            business = (date(2026, 11, 9) + timedelta(days=index)).isoformat()
            self.assertEqual(self.create(business_date=business, game=effective_games(business)[0]["game_id"]).status_code, 201)
        response = self.client.get("/api/payments/analytics/", {"group_by": "business_date", "game_page": 2})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["game_breakdown"]["count"], 21)
        self.assertEqual(len(response.data["game_breakdown"]["results"]), 1)
        self.assertEqual(response.data["number_breakdown"]["count"], 1)

    def test_database_constraint_rejects_duplicate_even_outside_api(self):
        self.assertEqual(self.create().status_code, 201)
        duplicate = copy(PaymentObligation.objects.get())
        duplicate.pk = None
        duplicate.obligation_number = "DUPLICATE-CONSTRAINT"
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentObligation.objects.bulk_create([duplicate])
        self.assertEqual(PaymentObligation.objects.count(), 1)

    def test_cancelled_and_removed_obligations_do_not_reserve_active_identity(self):
        created = self.create()
        obligation = PaymentObligation.objects.get(pk=created.data["id"])
        obligation.status = PaymentObligation.ObligationStatus.CANCELLED
        obligation.cancelled_by = self.admin
        obligation.cancelled_at = obligation.created_at
        obligation.cancellation_reason = "Incorrect entry"
        obligation.save()
        self.assertEqual(self.create().status_code, 201)

    def test_super_admin_removes_only_unpaid_records_with_reason_and_audit(self):
        created = self.create()
        obligation_id = created.data["id"]
        missing_reason = self.client.delete(f"/api/payment-obligations/{obligation_id}/")
        self.assertEqual(missing_reason.status_code, 400)
        removed = self.client.delete(f"/api/payment-obligations/{obligation_id}/", {"reason": "Entered in error"}, format="json")
        self.assertEqual(removed.status_code, 204)
        obligation = PaymentObligation.objects.get(pk=obligation_id)
        self.assertEqual((obligation.deleted_by, obligation.deletion_reason), (self.admin, "Entered in error"))
        self.assertIsNotNone(obligation.deleted_at)
        self.assertEqual(self.client.get("/api/payment-obligations/").data["count"], 0)
        self.assertEqual(self.pay(obligation_id, "removed-obligation-payment").status_code, 400)
        audit = AuditLog.objects.get(action="PAYMENT_OBLIGATION_DELETED")
        self.assertEqual(audit.object_id, str(obligation_id))
        self.assertEqual(audit.new_values["reason"], "Entered in error")
        replacement = self.create()
        self.assertEqual(replacement.status_code, 201, replacement.data)
        self.assertNotEqual(replacement.data["obligation_number"], created.data["obligation_number"])
        analytics = self.client.get("/api/payments/analytics/").data["obligation_portfolio"]
        self.assertEqual(analytics["obligation_count"], 1)
        self.assertEqual(analytics["total_expected"], "100.00")

    def test_accountant_cannot_remove_obligations(self):
        assignment = UserAgencyAssignment.objects.create(
            user=User.objects.create_user(email="no-delete@example.com", password="Testpass123!"),
            agency=self.agency,
            can_create=True,
            can_delete=True,
        )
        created = self.create()
        self.client.force_authenticate(assignment.user)
        denied = self.client.delete(
            f"/api/payment-obligations/{created.data['id']}/",
            {"reason": "Attempted removal"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
        self.assertIsNone(PaymentObligation.objects.get(pk=created.data["id"]).deleted_at)
        self.assertFalse(AuditLog.objects.filter(action="PAYMENT_OBLIGATION_DELETED").exists())

    def test_payment_and_reversal_history_prevent_removal(self):
        created = self.create()
        payment = self.pay(created.data["id"], "history-delete")
        denied_posted = self.client.delete(
            f"/api/payment-obligations/{created.data['id']}/",
            {"reason": "Cannot remove posted history"},
            format="json",
        )
        self.assertEqual(denied_posted.status_code, 400)
        reversed_response = self.client.post(
            f"/api/payer-payments/{payment.data['id']}/reverse/",
            {"reason": "Correction", "confirmed": True},
            format="json",
        )
        self.assertEqual(reversed_response.status_code, 200)
        denied_reversed = self.client.delete(
            f"/api/payment-obligations/{created.data['id']}/",
            {"reason": "Cannot remove reversed history"},
            format="json",
        )
        self.assertEqual(denied_reversed.status_code, 400)
        self.assertIsNone(PaymentObligation.objects.get(pk=created.data["id"]).deleted_at)
        self.assertEqual(PayerPayment.objects.filter(obligation_id=created.data["id"]).count(), 1)

    def test_game_snapshots_reject_model_and_bulk_mutation(self):
        from django.core.exceptions import ValidationError
        created = self.create()
        obligation = PaymentObligation.objects.get(pk=created.data["id"])
        payment_id = self.pay(obligation.pk, "immutable").data["id"]
        for obj in (obligation, PayerPayment.objects.get(pk=payment_id)):
            obj.game_snapshot = {"name": "Tampered"}
            with self.assertRaises(ValidationError):
                obj.save()
            with self.assertRaises(ValidationError):
                type(obj).objects.filter(pk=obj.pk).update(game_snapshot={"name": "Tampered"})
            with self.assertRaises(ValidationError):
                type(obj).objects.bulk_update([obj], ["game_snapshot"])

    def test_legacy_remains_payable_and_unassigned(self):
        legacy = PaymentObligation.objects.create(agency=self.agency, payer=self.payer, description="Old obligation", obligation_date="2026-01-01", total_expected="100.00", created_by=self.admin)
        response = self.pay(legacy.pk, "legacy")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data["game_snapshot"])
        receipt = self.client.get(f"/api/payer-payments/{response.data['id']}/receipt/")
        self.assertIn(b"Not assigned - legacy obligation.", receipt.content)


@unittest.skipUnless(connection.vendor == "postgresql", "Requires approved isolated local PostgreSQL")
class PaymentGameConcurrencyTests(GameFixture, TransactionTestCase):
    def test_concurrent_duplicate_creates_only_one(self):
        barrier = threading.Barrier(2)
        def attempt():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.admin)
                barrier.wait(timeout=10)
                return client.post("/api/payment-obligations/", self.payload, format="json").status_code
            finally:
                connections["default"].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(sorted(statuses), [201, 400])
        self.assertEqual(PaymentObligation.objects.count(), 1)


class PaymentGameMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_existing_rows_and_null_games(self):
        from django.db.migrations.executor import MigrationExecutor
        before = [("core", "0024_daily_sheet_commission_snapshot")]
        after = [("core", "0025_payment_game_snapshots")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            user = apps.get_model("core", "User").objects.create(email="legacy-migration@example.com")
            agency = apps.get_model("core", "Agency").objects.create(name="Legacy migration", code="legacy-migration")
            payer = apps.get_model("core", "PaymentPayer").objects.create(agency_id=agency.pk, payer_name="Legacy", created_by_id=user.pk)
            model = apps.get_model("core", "PaymentObligation")
            obligation = model.objects.create(agency_id=agency.pk, payer_id=payer.pk, created_by_id=user.pk, obligation_number="OLD-001", description="Historical", obligation_date=date(2026, 1, 1), total_expected="100.00")
            payment_model = apps.get_model("core", "PayerPayment")
            payment_model.objects.create(obligation_id=obligation.pk, receipt_number="OLD-PAY-001", agency_snapshot="Old Agency", payer_name_snapshot="Old Payer", obligation_number_snapshot="OLD-001", obligation_description_snapshot="Old description", obligation_date_snapshot=date(2026, 1, 1), expected_amount_snapshot="100.00", amount_previously_paid="0.00", amount_received="10.00", cumulative_amount_paid="10.00", balance_after_payment="90.00", payment_method="CASH", recorded_by_id=user.pk, idempotency_key="old-payment")
            old_obligations = list(model.objects.values())
            old_payments = list(payment_model.objects.values())
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            rows = list(apps.get_model("core", "PaymentObligation").objects.values())
            for row in rows:
                for key in ("game_id", "business_date", "game_id_snapshot", "game_snapshot", "creation_key"):
                    self.assertIsNone(row.pop(key))
            self.assertEqual(rows, old_obligations)
            rows = list(apps.get_model("core", "PayerPayment").objects.values())
            for row in rows:
                self.assertIsNone(row.pop("game_snapshot"))
            self.assertEqual(rows, old_payments)
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            self.assertEqual(list(model.objects.values()), old_obligations)
            self.assertEqual(list(payment_model.objects.values()), old_payments)
        finally:
            MigrationExecutor(connection).migrate(latest)
