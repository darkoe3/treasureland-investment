from datetime import date
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


BEFORE = [("core", "0028_game_category")]
AFTER = [("core", "0029_remove_paymentobligation_unique_payment_number_game_date_and_more")]


class PaymentObligationRemovalMigrationTests(TransactionTestCase):
    reset_sequences = True

    def test_0029_preserves_financial_rows_and_allows_only_valid_replacements(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(BEFORE)
            old_apps = MigrationExecutor(connection).loader.project_state(BEFORE).apps
            User = old_apps.get_model("core", "User")
            Agency = old_apps.get_model("core", "Agency")
            Person = old_apps.get_model("core", "Person")
            TPMCode = old_apps.get_model("core", "TPMCode")
            Game = old_apps.get_model("core", "Game")
            Payer = old_apps.get_model("core", "PaymentPayer")
            Obligation = old_apps.get_model("core", "PaymentObligation")
            Payment = old_apps.get_model("core", "PayerPayment")
            AuditLog = old_apps.get_model("core", "AuditLog")

            user = User.objects.create(
                email="migration-0029-admin@example.com",
                full_name="Migration Admin",
                role="SUPER_ADMIN",
                is_staff=True,
                is_superuser=True,
                is_active=True,
                password="!migration-test-password",
            )
            agency = Agency.objects.create(name="Migration Agency", code="migration-0029")
            person = Person.objects.create(agency_id=agency.pk, full_name="Migration Sub-Agent", agent_type="SUBAGENT")
            sub_agent = TPMCode.objects.create(person_id=person.pk, code="MIG-0029")
            game = Game.objects.create(name="Migration Timed Game", category="TIMED", is_active=True)
            payer = Payer.objects.create(
                agency_id=agency.pk,
                payer_name="Migration Payer",
                created_by_id=user.pk,
            )

            def obligation(number, business_date, status, description):
                return Obligation.objects.create(
                    agency_id=agency.pk,
                    payer_id=payer.pk,
                    sub_agent_number_id=sub_agent.pk,
                    obligation_number=number,
                    description=description,
                    obligation_date=business_date,
                    business_date=business_date,
                    total_expected=Decimal("100.00"),
                    status=status,
                    created_by_id=user.pk,
                    game_id=game.pk,
                    game_id_snapshot=game.pk,
                    game_snapshot={"id": game.pk, "name": game.name, "category": "TIMED"},
                    **(
                        {
                            "cancelled_by_id": user.pk,
                            "cancelled_at": timezone.now(),
                            "cancellation_reason": "Pre-migration cancellation",
                        }
                        if status == "CANCELLED"
                        else {}
                    ),
                )

            cancelled = obligation("MIG-OBL-CANCELLED", date(2026, 10, 1), "CANCELLED", "Cancelled before migration")
            financial = obligation("MIG-OBL-FINANCIAL", date(2026, 10, 2), "PARTIALLY_PAID", "Payment history before migration")
            posted = Payment.objects.create(
                obligation_id=financial.pk,
                receipt_number="MIG-REC-POSTED",
                agency_snapshot=agency.name,
                payer_name_snapshot=payer.payer_name,
                obligation_number_snapshot=financial.obligation_number,
                obligation_description_snapshot=financial.description,
                obligation_date_snapshot=financial.obligation_date,
                expected_amount_snapshot=Decimal("100.00"),
                amount_previously_paid=Decimal("0.00"),
                amount_received=Decimal("25.00"),
                cumulative_amount_paid=Decimal("25.00"),
                balance_after_payment=Decimal("75.00"),
                payment_method="CASH",
                recorded_by_id=user.pk,
                idempotency_key="migration-0029-posted",
            )
            reversed_payment = Payment.objects.create(
                obligation_id=financial.pk,
                receipt_number="MIG-REC-REVERSED",
                agency_snapshot=agency.name,
                payer_name_snapshot=payer.payer_name,
                obligation_number_snapshot=financial.obligation_number,
                obligation_description_snapshot=financial.description,
                obligation_date_snapshot=financial.obligation_date,
                expected_amount_snapshot=Decimal("100.00"),
                amount_previously_paid=Decimal("25.00"),
                amount_received=Decimal("10.00"),
                cumulative_amount_paid=Decimal("35.00"),
                balance_after_payment=Decimal("65.00"),
                payment_method="CASH",
                recorded_by_id=user.pk,
                idempotency_key="migration-0029-reversed",
                status="REVERSED",
                reversed_by_id=user.pk,
                reversed_at=timezone.now(),
                reversal_reason="Pre-migration reversal",
            )
            audit = AuditLog.objects.create(
                user_id=user.pk,
                action="PAYMENT_OBLIGATION_CANCELLED",
                model_name="PaymentObligation",
                object_id=str(cancelled.pk),
                new_values={"reason": "Pre-migration cancellation"},
            )

            obligations_before = list(Obligation.objects.order_by("pk").values())
            payments_before = list(Payment.objects.order_by("pk").values())
            audit_before = list(AuditLog.objects.order_by("pk").values())
            ids_before = {
                "agency": agency.pk,
                "payer": payer.pk,
                "sub_agent": sub_agent.pk,
                "game": game.pk,
                "cancelled": cancelled.pk,
                "financial": financial.pk,
                "posted_payment": posted.pk,
                "reversed_payment": reversed_payment.pk,
                "audit": audit.pk,
            }

            MigrationExecutor(connection).migrate(AFTER)
            current_apps = MigrationExecutor(connection).loader.project_state(AFTER).apps
            CurrentObligation = current_apps.get_model("core", "PaymentObligation")
            CurrentPayment = current_apps.get_model("core", "PayerPayment")
            CurrentAuditLog = current_apps.get_model("core", "AuditLog")

            obligations_after = list(CurrentObligation.objects.order_by("pk").values())
            for row in obligations_after:
                self.assertIsNone(row.pop("deleted_at"))
                self.assertIsNone(row.pop("deleted_by_id"))
                self.assertEqual(row.pop("deletion_reason"), "")
            self.assertEqual(obligations_after, obligations_before)
            self.assertEqual(list(CurrentPayment.objects.order_by("pk").values()), payments_before)
            self.assertEqual(list(CurrentAuditLog.objects.order_by("pk").values()), audit_before)

            preserved = CurrentObligation.objects.get(pk=ids_before["financial"])
            self.assertEqual(preserved.agency_id, ids_before["agency"])
            self.assertEqual(preserved.payer_id, ids_before["payer"])
            self.assertEqual(preserved.sub_agent_number_id, ids_before["sub_agent"])
            self.assertEqual(preserved.game_id, ids_before["game"])
            self.assertEqual(
                set(CurrentPayment.objects.filter(obligation_id=preserved.pk).values_list("status", flat=True)),
                {"POSTED", "REVERSED"},
            )

            cancelled_after = CurrentObligation.objects.get(pk=ids_before["cancelled"])
            replacement = CurrentObligation.objects.create(
                agency_id=cancelled_after.agency_id,
                payer_id=cancelled_after.payer_id,
                sub_agent_number_id=cancelled_after.sub_agent_number_id,
                obligation_number="MIG-OBL-REPLACEMENT",
                description="Replacement after migration",
                obligation_date=cancelled_after.obligation_date,
                business_date=cancelled_after.business_date,
                total_expected=cancelled_after.total_expected,
                status="OPEN",
                created_by_id=user.pk,
                game_id=cancelled_after.game_id,
                game_id_snapshot=cancelled_after.game_id_snapshot,
                game_snapshot=cancelled_after.game_snapshot,
            )
            self.assertEqual(replacement.business_date, cancelled_after.business_date)
            with self.assertRaises(IntegrityError), transaction.atomic():
                CurrentObligation.objects.create(
                    agency_id=cancelled_after.agency_id,
                    payer_id=cancelled_after.payer_id,
                    sub_agent_number_id=cancelled_after.sub_agent_number_id,
                    obligation_number="MIG-OBL-DUPLICATE",
                    description="Duplicate active obligation",
                    obligation_date=cancelled_after.obligation_date,
                    business_date=cancelled_after.business_date,
                    total_expected=cancelled_after.total_expected,
                    status="OPEN",
                    created_by_id=user.pk,
                    game_id=cancelled_after.game_id,
                    game_id_snapshot=cancelled_after.game_id_snapshot,
                    game_snapshot=cancelled_after.game_snapshot,
                )
        finally:
            MigrationExecutor(connection).migrate(latest)
