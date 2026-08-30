from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import (
    Agency,
    AgentType,
    AuditLog,
    DailySheet,
    DailySheetStatus,
    Game,
    OmittedTerminal,
    Person,
    TPMCode,
    TPMDailyTransaction,
    TransactionGameSale,
    UserAgencyAssignment,
    WeeklyGameSchedule,
    money,
)


User = get_user_model()


class Phase4Mixin:
    def setUpBase(self):
        self.admin = User.objects.create_superuser("admin@example.com", "AdminPass123!", full_name="Admin")
        self.acct = User.objects.create_user("acct@example.com", "AcctPass123!", full_name="Acct")
        self.other = User.objects.create_user("other@example.com", "OtherPass123!", full_name="Other")
        self.musa = Agency.objects.create(name="Musa 1", code="musa-1")
        self.sango = Agency.objects.create(name="Sango", code="sango")
        self.assignment = UserAgencyAssignment.objects.create(
            user=self.acct,
            agency=self.musa,
            can_create=True,
            can_edit=True,
            can_delete=True,
            can_view_history=True,
        )
        UserAgencyAssignment.objects.create(user=self.other, agency=self.sango, can_create=True, can_edit=True)
        self.person = Person.objects.create(agency=self.musa, full_name="Ayo", agent_type=AgentType.MAIN_AGENT)
        self.sub = Person.objects.create(agency=self.musa, full_name="Bisi", agent_type=AgentType.SUBAGENT)
        self.tpm_a = TPMCode.objects.create(person=self.person, code="TPM-A")
        self.tpm_b = TPMCode.objects.create(person=self.person, code="TPM-B")
        self.tpm_sub = TPMCode.objects.create(person=self.sub, code="SUB-A")
        self.other_person = Person.objects.create(agency=self.sango, full_name="Hidden", agent_type=AgentType.MAIN_AGENT)
        self.other_tpm = TPMCode.objects.create(person=self.other_person, code="HIDDEN")
        self.game = Game.objects.create(name="Premier")
        self.game2 = Game.objects.create(name="Lucky")
        WeeklyGameSchedule.objects.create(game=self.game, weekday=1, closing_time=time(10), draw_time=time(11), display_order=1)
        WeeklyGameSchedule.objects.create(game=self.game2, weekday=1, closing_time=time(12), draw_time=time(13), display_order=2)

    def sheet(self, incoming="142.50", tax="0.00"):
        sheet = DailySheet.objects.create(
            agency=self.musa,
            transaction_date=date(2026, 8, 24),
            incoming_funds=Decimal(incoming),
            tax=Decimal(tax),
            created_by=self.acct,
        )
        sheet.copy_weekday_games()
        return sheet

    def txn(self, sheet, tpm, first="100.00", second="50.00"):
        txn = TPMDailyTransaction.objects.create(daily_sheet=sheet, tpm_code=tpm, created_by=self.acct, updated_by=self.acct)
        games = list(sheet.sheet_games.order_by("display_order"))
        TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=games[0], amount=Decimal(first))
        TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=games[1], amount=Decimal(second))
        return txn


class Phase4ModelTests(Phase4Mixin, TestCase):
    def setUp(self):
        self.setUpBase()

    def test_case_insensitive_tpm_code_uniqueness(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TPMCode.objects.create(person=self.person, code="tpm-a")

    def test_manual_tax_does_not_change_calculated_to_pay(self):
        sheet = self.sheet(incoming="142.50", tax="99.99")
        self.txn(sheet, self.tpm_a)
        self.assertEqual(sheet.totals()["total_to_pay"], Decimal("142.50"))
        self.assertEqual(sheet.totals()["tax"], Decimal("99.99"))
        self.assertEqual(sheet.totals()["variance"], Decimal("0.00"))

    def test_round_half_up_edge_case(self):
        self.assertEqual(money(Decimal("1.005")), Decimal("1.01"))

    def test_omission_soft_delete_preserves_history(self):
        sheet = self.sheet()
        omission = OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_a, reason="Closed", recorded_by=self.acct)
        omission.is_active = False
        omission.save()
        self.assertTrue(OmittedTerminal.objects.filter(pk=omission.pk).exists())


class Phase4APITests(Phase4Mixin, APITestCase):
    def setUp(self):
        self.setUpBase()

    def test_accountant_people_permissions_are_independent(self):
        self.client.force_authenticate(self.acct)
        ok = self.client.post("/api/people/", {"agency": self.musa.id, "full_name": "New", "agent_type": "MAIN_AGENT"})
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)
        self.assignment.can_create = False
        self.assignment.save()
        blocked = self.client.post("/api/people/", {"agency": self.musa.id, "full_name": "Blocked", "agent_type": "MAIN_AGENT"})
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)

    def test_accountant_cannot_cross_agency_people_or_tpm_writes(self):
        self.client.force_authenticate(self.acct)
        patch = self.client.patch(f"/api/people/{self.other_person.id}/", {"full_name": "Changed"})
        create_code = self.client.post("/api/tpm-codes/", {"person": self.other_person.id, "code": "NOPE"})
        self.assertEqual(patch.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(create_code.status_code, status.HTTP_403_FORBIDDEN)

    def test_safe_deactivation_preserves_transaction_history(self):
        sheet = self.sheet()
        self.txn(sheet, self.tpm_a)
        self.client.force_authenticate(self.acct)
        response = self.client.delete(f"/api/tpm-codes/{self.tpm_a.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.tpm_a.refresh_from_db()
        self.assertFalse(self.tpm_a.is_active)
        self.assertTrue(TPMDailyTransaction.objects.filter(tpm_code=self.tpm_a).exists())

    def test_missing_expected_terminal_reporting_and_omission_validation(self):
        sheet = self.sheet()
        self.txn(sheet, self.tpm_a)
        self.client.force_authenticate(self.acct)
        summary = self.client.get(f"/api/daily-sheets/{sheet.id}/summary/")
        missing_codes = {item["code"] for item in summary.data["omitted_terminals"]["items"]}
        self.assertIn("TPM-B", missing_codes)
        no_reason = self.client.post("/api/omitted-terminals/", {"daily_sheet": sheet.id, "tpm_code": self.tpm_b.id, "reason": ""})
        self.assertEqual(no_reason.status_code, status.HTTP_400_BAD_REQUEST)

    def test_combined_person_total_and_subagent_split(self):
        sheet = self.sheet(incoming="237.50")
        self.txn(sheet, self.tpm_a, "100.00", "0.00")
        self.txn(sheet, self.tpm_b, "50.00", "0.00")
        self.txn(sheet, self.tpm_sub, "100.00", "0.00")
        summary = self.client.force_authenticate(self.admin) or self.client.get(f"/api/daily-sheets/{sheet.id}/summary/")
        ayo = next(item for item in summary.data["person_totals"] if item["person_name"] == "Ayo")
        self.assertEqual(Decimal(ayo["to_pay"]), Decimal("142.50"))
        self.assertEqual(Decimal(summary.data["subagent_share"]), Decimal("2.00"))
        self.assertEqual(Decimal(summary.data["organisation_share_on_subagent_sales"]), Decimal("3.00"))

    def test_workflow_rules_and_audit_entries(self):
        sheet = self.sheet(incoming="0.00")
        self.txn(sheet, self.tpm_a, "0.00", "0.00")
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_b, reason="Closed", recorded_by=self.acct)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_sub, reason="Closed", recorded_by=self.acct)
        self.client.force_authenticate(self.acct)
        submit = self.client.post(f"/api/daily-sheets/{sheet.id}/submit/")
        self.assertEqual(submit.status_code, status.HTTP_200_OK)
        locked = self.client.patch(f"/api/daily-sheets/{sheet.id}/", {"tax": "1.00"})
        self.assertEqual(locked.status_code, status.HTTP_400_BAD_REQUEST)
        self.client.force_authenticate(self.admin)
        returned = self.client.post(f"/api/daily-sheets/{sheet.id}/return/", {"return_comment": "Check"})
        self.assertEqual(returned.status_code, status.HTTP_200_OK)
        sheet.refresh_from_db()
        sheet.status = DailySheetStatus.SUBMITTED
        sheet.save()
        approved = self.client.post(f"/api/daily-sheets/{sheet.id}/approve/")
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        reopened = self.client.post(f"/api/daily-sheets/{sheet.id}/reopen/", {"reopen_reason": "Late correction"})
        self.assertEqual(reopened.status_code, status.HTTP_200_OK)
        self.assertTrue(AuditLog.objects.filter(daily_sheet=sheet, action="SHEET_REOPENED").exists())
