from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APITestCase

from core.models import (Agency, AuditAction, AuditLog, DailySheet, DailySheetGame,
    DailySheetImportBatch, Game, OmittedTerminal, Person, TPMCode,
    TPMDailyTransaction, TransactionGameSale, User)


class SheetSafetyTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("safe@example.com", "safe-password-123", full_name="Admin")
        self.accountant = User.objects.create_user("acct@example.com", "safe-password-123", full_name="Accountant")
        self.agency = Agency.objects.create(name="Safety", code="safety")
        self.sheet = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 8, 27), created_by=self.admin)
        self.game = DailySheetGame.objects.create(daily_sheet=self.sheet, game=Game.objects.create(name="Historical"), game_name_snapshot="Original", is_whole_day_snapshot=True)
        self.person = Person.objects.create(agency=self.agency, full_name="Person", agent_type="SUBAGENT")
        self.tpm = TPMCode.objects.create(person=self.person, code="SAFE1")
        self.client.force_authenticate(self.admin)
        self.url = f"/api/daily-sheets/{self.sheet.pk}/"

    def reset(self, **values):
        return self.client.post(self.url + "reset/", {"reason": "Clear test entries", "confirm_reset": True, **values}, format="json")

    def delete(self, **values):
        return self.client.delete(self.url, {"reason": "Unused test sheet", "confirm_permanent_delete": True, **values}, format="json")

    def populate(self):
        txn = TPMDailyTransaction.objects.create(daily_sheet=self.sheet, tpm_code=self.tpm, created_by=self.admin, updated_by=self.admin)
        TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=self.game, amount=100)
        omitted = TPMCode.objects.create(person=self.person, code="SAFE2")
        OmittedTerminal.objects.create(daily_sheet=self.sheet, tpm_code=omitted, reason="Test", recorded_by=self.admin)
        self.sheet.incoming_funds = 95
        self.sheet.tax = 2
        self.sheet.reconciliation_note = "Temporary"
        self.sheet.save()

    def test_reset_editable_statuses_preserves_history_and_snapshots(self):
        snapshots = list(self.sheet.sheet_games.values())
        for state in ["DRAFT", "RETURNED", "REOPENED"]:
            with self.subTest(status=state):
                self.populate()
                self.sheet.status = state
                self.sheet.return_comment = "Previous return"
                self.sheet.reopen_reason = "Previous reopen"
                self.sheet.returned_at = timezone.now()
                self.sheet.save()
                history = AuditLog.objects.create(user=self.admin, agency=self.agency, daily_sheet=self.sheet, action=AuditAction.SHEET_RETURNED, model_name="DailySheet", object_id=str(self.sheet.pk))
                response = self.reset()
                self.assertEqual(response.status_code, 200, response.data)
                self.sheet.refresh_from_db()
                self.assertEqual(self.sheet.status, state)
                self.assertEqual(self.sheet.return_comment, "Previous return")
                self.assertEqual(self.sheet.reopen_reason, "Previous reopen")
                self.assertIsNotNone(self.sheet.returned_at)
                self.assertTrue(AuditLog.objects.filter(pk=history.pk).exists())
                self.assertEqual(list(self.sheet.sheet_games.values()), snapshots)
                self.assertEqual(self.sheet.agency_id, self.agency.pk)
                self.assertEqual(self.sheet.transaction_date, date(2026, 8, 27))
                self.assertEqual(self.sheet.created_by_id, self.admin.pk)
                self.assertFalse(self.sheet.transactions.exists())
                self.assertFalse(TransactionGameSale.objects.exists())
                self.assertFalse(self.sheet.omitted_terminals.exists())
                self.assertIsNone(self.sheet.incoming_funds)
                self.assertIsNone(self.sheet.tax)
                self.assertEqual(self.sheet.reconciliation_note, "")
                for key in ["gross_sales", "commission", "total_to_pay", "subagent_share", "organisation_share_on_subagent_sales", "variance"]:
                    self.assertEqual(self.sheet.totals()[key], Decimal("0.00"))
                TPMCode.objects.filter(code="SAFE2").delete()

    def test_reset_summary_is_safe_and_second_reset_is_audited(self):
        self.populate()
        self.assertEqual(self.reset().status_code, 200)
        event = AuditLog.objects.get(action=AuditAction.DAILY_SHEET_RESET)
        self.assertEqual(set(event.old_values), {"daily_sheet_id", "agency_id", "agency_name", "transaction_date", "actor", "reason", "previous_transaction_count", "previous_omission_count", "previous_net_sales", "previous_to_pay", "timestamp"})
        self.assertEqual(event.old_values["previous_transaction_count"], 1)
        self.assertEqual(event.old_values["previous_omission_count"], 1)
        self.assertEqual(event.old_values["previous_net_sales"], "100.00")
        self.assertEqual(event.old_values["previous_to_pay"], "95.00")
        self.assertEqual(self.reset().status_code, 200)
        self.assertEqual(AuditLog.objects.filter(action=AuditAction.DAILY_SHEET_RESET).count(), 2)
        self.assertFalse(self.delete().status_code == 204)

    def test_reset_rejections(self):
        for state in ["SUBMITTED", "APPROVED"]:
            self.sheet.status = state
            self.sheet.save()
            self.assertEqual(self.reset().status_code, 400)
        self.sheet.status = "DRAFT"
        self.sheet.is_archived = True
        self.sheet.save()
        self.assertEqual(self.reset().status_code, 400)
        self.sheet.is_archived = False
        self.sheet.save()
        for reason in ["", "   ", None, 42]:
            self.assertEqual(self.reset(reason=reason).status_code, 400)
        for confirmation in [False, None, "true", 1]:
            self.assertEqual(self.reset(confirm_reset=confirmation).status_code, 400)
        self.assertEqual(self.client.post(self.url + "reset/", {}, format="json").status_code, 400)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.reset().status_code, 403)
        self.assertEqual(self.delete().status_code, 403)

    def test_eligible_delete_preserves_creation_and_deletion_audits(self):
        history = AuditLog.objects.create(user=self.admin, agency=self.agency, daily_sheet=self.sheet, action=AuditAction.SHEET_CREATED, model_name="DailySheet", object_id=str(self.sheet.pk))
        self.assertTrue(self.sheet.can_delete)
        self.assertEqual(self.delete().status_code, 204)
        self.assertFalse(DailySheet.objects.filter(pk=self.sheet.pk).exists())
        history.refresh_from_db()
        self.assertIsNone(history.daily_sheet_id)
        event = AuditLog.objects.get(action=AuditAction.DAILY_SHEET_DELETED)
        self.assertEqual(event.old_values["daily_sheet_id"], self.sheet.pk)
        self.assertTrue(Agency.objects.filter(pk=self.agency.pk).exists())
        self.assertTrue(TPMCode.objects.filter(pk=self.tpm.pk).exists())

    def test_delete_rejects_data_history_archive_and_confirmation_errors(self):
        for field, value in [("incoming_funds", 0), ("tax", 0), ("reconciliation_note", "note"), ("submitted_at", timezone.now()), ("return_comment", "old"), ("reopen_reason", "old"), ("is_archived", True), ("status", "RETURNED")]:
            original = getattr(self.sheet, field)
            setattr(self.sheet, field, value)
            self.sheet.save()
            response = self.delete()
            self.assertEqual(response.status_code, 400)
            self.assertEqual(str(response.data["detail"]), "This daily sheet cannot be deleted. Reset or archive it instead.")
            setattr(self.sheet, field, original)
            self.sheet.save()
        self.assertEqual(self.delete(reason=" ").status_code, 400)
        self.assertEqual(self.delete(confirm_permanent_delete=False).status_code, 400)
        self.populate()
        self.assertEqual(self.delete().status_code, 400)

    def test_confirmed_import_reference_preserved(self):
        batch = DailySheetImportBatch.objects.create(uploader=self.admin, agency=self.agency, transaction_date=self.sheet.transaction_date, original_filename="test.xlsx", file_hash="a" * 64, status="CONFIRMED", confirmed_sheet=self.sheet, confirmed_at=timezone.now(), expires_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(self.delete().status_code, 400)
        self.assertEqual(self.reset().status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.confirmed_sheet_id, self.sheet.pk)
        self.assertEqual(batch.status, "CONFIRMED")
        self.assertEqual(self.client.post(f"/api/daily-sheet-imports/{batch.pk}/confirm/", {}, format="json").status_code, 400)

    def test_reset_rolls_back_if_audit_fails(self):
        self.populate()
        with patch("core.views.log_audit", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.reset()
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.transactions.count(), 1)
        self.assertEqual(self.sheet.omitted_terminals.count(), 1)
        self.assertEqual(self.sheet.incoming_funds, 95)

    def test_reset_is_scoped_to_selected_sheet(self):
        self.populate()
        other = DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 8, 28), created_by=self.admin, incoming_funds=50, tax=1)
        txn = TPMDailyTransaction.objects.create(daily_sheet=other, tpm_code=self.tpm, created_by=self.admin, updated_by=self.admin)
        self.assertEqual(self.reset().status_code, 200)
        other.refresh_from_db()
        self.assertEqual(other.incoming_funds, 50)
        self.assertEqual(other.tax, 1)
        self.assertTrue(TPMDailyTransaction.objects.filter(pk=txn.pk).exists())
        self.assertTrue(Person.objects.filter(pk=self.person.pk).exists())
        self.assertEqual(User.objects.count(), 2)

    def test_omissions_and_past_financial_audits_block_delete(self):
        omission = OmittedTerminal.objects.create(daily_sheet=self.sheet, tpm_code=self.tpm, reason="Test", recorded_by=self.admin)
        self.assertEqual(self.delete().status_code, 400)
        omission.delete()
        AuditLog.objects.create(user=self.admin, agency=self.agency, daily_sheet=self.sheet, action=AuditAction.INCOMING_FUNDS_CHANGED, model_name="DailySheet", object_id=str(self.sheet.pk))
        self.assertEqual(self.delete().status_code, 400)
