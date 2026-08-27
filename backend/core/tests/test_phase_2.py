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
    UserRole,
    WeeklyGameSchedule,
)
from core.serializers import TPMDailyTransactionSerializer


User = get_user_model()


class Phase2Mixin:
    def build_base(self):
        self.super_admin = User.objects.create_superuser("admin@example.com", "pass-12345", full_name="Admin")
        self.accountant = User.objects.create_user("acct@example.com", "pass-12345", full_name="Acct")
        self.other_accountant = User.objects.create_user("other@example.com", "pass-12345", full_name="Other")
        self.agency = Agency.objects.create(name="Musa 1", code="musa-1")
        self.other_agency = Agency.objects.create(name="Sango", code="sango")
        self.assignment = UserAgencyAssignment.objects.create(
            user=self.accountant,
            agency=self.agency,
            can_create=True,
            can_edit=True,
            can_delete=True,
            can_view_history=True,
        )
        self.other_assignment = UserAgencyAssignment.objects.create(user=self.other_accountant, agency=self.other_agency)
        self.main_person = Person.objects.create(agency=self.agency, full_name="Dele", agent_type=AgentType.MAIN_AGENT)
        self.sub_person = Person.objects.create(agency=self.agency, full_name="Sub Dele", agent_type=AgentType.SUBAGENT)
        self.other_person = Person.objects.create(agency=self.other_agency, full_name="Other Person", agent_type=AgentType.MAIN_AGENT)
        self.tpm_one = TPMCode.objects.create(person=self.main_person, code="513670124")
        self.tpm_two = TPMCode.objects.create(person=self.main_person, code="513670125")
        self.sub_tpm = TPMCode.objects.create(person=self.sub_person, code="SUB001")
        self.other_tpm = TPMCode.objects.create(person=self.other_person, code="OTHER001")
        self.game_one = Game.objects.create(name="Premier")
        self.game_two = Game.objects.create(name="Lucky")
        WeeklyGameSchedule.objects.create(
            game=self.game_one,
            weekday=1,
            closing_time=time(10, 0),
            draw_time=time(11, 0),
            display_order=1,
        )
        WeeklyGameSchedule.objects.create(
            game=self.game_two,
            weekday=1,
            closing_time=time(12, 0),
            draw_time=time(13, 0),
            display_order=2,
        )

    def create_sheet(self, incoming="142500.00", tax="0.00"):
        sheet = DailySheet.objects.create(
            agency=self.agency,
            transaction_date=date(2026, 8, 24),
            incoming_funds=Decimal(incoming),
            tax=Decimal(tax),
            created_by=self.accountant,
        )
        sheet.copy_weekday_games()
        return sheet

    def sales_payload(self, sheet, first="0.00", second="0.00"):
        games = list(sheet.sheet_games.order_by("display_order"))
        return [
            {"daily_sheet_game": games[0].id, "amount": first},
            {"daily_sheet_game": games[1].id, "amount": second},
        ]

    def create_transaction(self, sheet, tpm_code, first="0.00", second="0.00"):
        txn = TPMDailyTransaction.objects.create(
            daily_sheet=sheet,
            tpm_code=tpm_code,
            created_by=self.accountant,
            updated_by=self.accountant,
        )
        games = list(sheet.sheet_games.order_by("display_order"))
        TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=games[0], amount=Decimal(first))
        TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=games[1], amount=Decimal(second))
        return txn


class Phase2ModelTests(Phase2Mixin, TestCase):
    def setUp(self):
        self.build_base()

    def test_daily_sheet_copies_correct_weekday_game_schedule(self):
        sheet = self.create_sheet()
        self.assertEqual(list(sheet.sheet_games.values_list("game_name_snapshot", flat=True)), ["Premier", "Lucky"])

    def test_historical_daily_sheet_game_snapshots_remain_unchanged(self):
        sheet = self.create_sheet()
        schedule = WeeklyGameSchedule.objects.get(game=self.game_one)
        self.game_one.name = "Premier Changed"
        self.game_one.save()
        schedule.closing_time = time(9, 0)
        schedule.draw_time = time(10, 0)
        schedule.save()
        snapshot = sheet.sheet_games.order_by("display_order").first()
        self.assertEqual(snapshot.game_name_snapshot, "Premier")
        self.assertEqual(snapshot.closing_time_snapshot, time(10, 0))

    def test_one_sheet_per_agency_and_date(self):
        self.create_sheet()
        with self.assertRaises(Exception), transaction.atomic():
            self.create_sheet()

    def test_tpm_code_must_belong_to_sheet_agency(self):
        sheet = self.create_sheet()
        with self.assertRaises(Exception):
            TPMDailyTransaction.objects.create(
                daily_sheet=sheet,
                tpm_code=self.other_tpm,
                created_by=self.accountant,
                updated_by=self.accountant,
            )

    def test_duplicate_tpm_transaction_is_rejected(self):
        sheet = self.create_sheet()
        self.create_transaction(sheet, self.tpm_one)
        with self.assertRaises(Exception), transaction.atomic():
            TPMDailyTransaction.objects.create(
                daily_sheet=sheet,
                tpm_code=self.tpm_one,
                created_by=self.accountant,
                updated_by=self.accountant,
            )

    def test_duplicate_transaction_game_sale_is_rejected(self):
        sheet = self.create_sheet()
        txn = self.create_transaction(sheet, self.tpm_one)
        with self.assertRaises(Exception), transaction.atomic():
            TransactionGameSale.objects.create(
                transaction=txn,
                daily_sheet_game=sheet.sheet_games.first(),
                amount=Decimal("1.00"),
            )

    def test_negative_amounts_are_rejected(self):
        sheet = self.create_sheet()
        txn = TPMDailyTransaction.objects.create(
            daily_sheet=sheet,
            tpm_code=self.tpm_one,
            created_by=self.accountant,
            updated_by=self.accountant,
        )
        with self.assertRaises(Exception):
            TransactionGameSale.objects.create(transaction=txn, daily_sheet_game=sheet.sheet_games.first(), amount=Decimal("-1.00"))
        with self.assertRaises(Exception):
            DailySheet.objects.create(agency=self.agency, transaction_date=date(2026, 8, 25), incoming_funds=Decimal("-1.00"), tax=0, created_by=self.accountant)

    def test_transaction_calculations(self):
        sheet = self.create_sheet()
        txn = self.create_transaction(sheet, self.tpm_one, "60000.00", "40000.00")
        self.assertEqual(txn.net_sales, Decimal("100000.00"))
        self.assertEqual(txn.commission, Decimal("5000.00"))
        self.assertEqual(txn.to_pay, Decimal("95000.00"))

    def test_person_total_combines_multiple_tpm_codes(self):
        sheet = self.create_sheet()
        txn = self.create_transaction(sheet, self.tpm_one, "100000.00", "0.00")
        self.create_transaction(sheet, self.tpm_two, "50000.00", "0.00")
        data = TPMDailyTransactionSerializer(txn).data
        self.assertEqual(Decimal(data["person_total"]), Decimal("142500.00"))

    def test_daily_summary_calculations(self):
        sheet = self.create_sheet(incoming="142000.00", tax="100.00")
        self.create_transaction(sheet, self.tpm_one, "100000.00", "0.00")
        self.create_transaction(sheet, self.sub_tpm, "50000.00", "0.00")
        totals = sheet.totals()
        self.assertEqual(totals["gross_sales"], Decimal("150000.00"))
        self.assertEqual(totals["total_to_pay"], Decimal("142500.00"))
        self.assertEqual(totals["commission"], Decimal("7500.00"))
        self.assertEqual(totals["subagent_sales"], Decimal("50000.00"))
        self.assertEqual(totals["subagent_share"], Decimal("1000.00"))
        self.assertEqual(totals["organisation_share_on_subagent_sales"], Decimal("1500.00"))
        self.assertEqual(totals["commission_minus_tax"], Decimal("7400.00"))
        self.assertEqual(totals["premier_office_payment"], Decimal("134600.00"))
        self.assertEqual(totals["variance"], Decimal("-500.00"))
        self.assertEqual(totals["variance_status"], "SHORTFALL")

    def test_variance_statuses(self):
        balanced = self.create_sheet(incoming="0.00")
        self.assertEqual(balanced.totals()["variance_status"], "BALANCED")
        balanced.incoming_funds = Decimal("1.00")
        balanced.save()
        self.assertEqual(balanced.totals()["variance_status"], "EXCESS")


class Phase2APITests(Phase2Mixin, APITestCase):
    def setUp(self):
        self.build_base()

    def test_accountant_cannot_create_sheet_for_unassigned_agency(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.post(
            "/api/daily-sheets/",
            {"agency": self.other_agency.id, "transaction_date": "2026-08-24", "incoming_funds": "0.00", "tax": "0.00"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_accountant_permission_flags_are_enforced(self):
        self.assignment.can_create = False
        self.assignment.save()
        self.client.force_authenticate(self.accountant)
        response = self.client.post(
            "/api/daily-sheets/",
            {"agency": self.agency.id, "transaction_date": "2026-08-24", "incoming_funds": "0.00", "tax": "0.00"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_nested_transaction_create_and_atomic_duplicate_validation(self):
        sheet = self.create_sheet()
        self.client.force_authenticate(self.accountant)
        response = self.client.post(
            "/api/tpm-daily-transactions/",
            {"daily_sheet": sheet.id, "tpm_code": self.tpm_one.id, "sales": self.sales_payload(sheet, "23270.00", "13805.00")},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        bad = self.client.post(
            "/api/tpm-daily-transactions/",
            {
                "daily_sheet": sheet.id,
                "tpm_code": self.tpm_two.id,
                "sales": [
                    {"daily_sheet_game": sheet.sheet_games.first().id, "amount": "1.00"},
                    {"daily_sheet_game": sheet.sheet_games.first().id, "amount": "2.00"},
                ],
            },
            format="json",
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(TPMDailyTransaction.objects.filter(tpm_code=self.tpm_two).exists())

    def test_zero_total_entered_and_omitted_terminal_summary(self):
        sheet = self.create_sheet()
        self.create_transaction(sheet, self.tpm_one, "0.00", "0.00")
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_two, reason="Closed", recorded_by=self.accountant)
        self.client.force_authenticate(self.accountant)
        response = self.client.get(f"/api/daily-sheets/{sheet.id}/summary/")
        self.assertEqual(response.data["zero_sales_count"], 1)
        self.assertEqual(response.data["total_terminals"], 3)
        self.assertEqual(response.data["entered_terminals"], 1)
        self.assertEqual(response.data["omitted_terminals"]["count"], 2)

    def test_tpm_code_cannot_be_both_entered_and_omitted(self):
        sheet = self.create_sheet()
        self.create_transaction(sheet, self.tpm_one)
        self.client.force_authenticate(self.accountant)
        response = self.client.post(
            "/api/omitted-terminals/",
            {"daily_sheet": sheet.id, "tpm_code": self.tpm_one.id, "reason": "No sales"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submission_fails_when_terminals_are_unexplained(self):
        sheet = self.create_sheet()
        self.create_transaction(sheet, self.tpm_one)
        self.client.force_authenticate(self.accountant)
        response = self.client.post(f"/api/daily-sheets/{sheet.id}/submit/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submission_fails_when_variance_without_note(self):
        sheet = self.create_sheet(incoming="1.00")
        self.create_transaction(sheet, self.tpm_one)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_two, reason="Closed", recorded_by=self.accountant)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.sub_tpm, reason="Closed", recorded_by=self.accountant)
        self.client.force_authenticate(self.accountant)
        response = self.client.post(f"/api/daily-sheets/{sheet.id}/submit/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submission_succeeds_when_all_rules_are_satisfied(self):
        sheet = self.create_sheet(incoming="0.00")
        self.create_transaction(sheet, self.tpm_one)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_two, reason="Closed", recorded_by=self.accountant)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.sub_tpm, reason="Closed", recorded_by=self.accountant)
        self.client.force_authenticate(self.accountant)
        response = self.client.post(f"/api/daily-sheets/{sheet.id}/submit/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], DailySheetStatus.SUBMITTED)

    def test_submitted_sheets_are_locked_against_accountant_changes(self):
        sheet = self.create_sheet(incoming="0.00")
        self.create_transaction(sheet, self.tpm_one)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_two, reason="Closed", recorded_by=self.accountant)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.sub_tpm, reason="Closed", recorded_by=self.accountant)
        sheet.status = DailySheetStatus.SUBMITTED
        sheet.save()
        self.client.force_authenticate(self.accountant)
        response = self.client.patch(f"/api/daily-sheets/{sheet.id}/", {"incoming_funds": "1.00"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_super_admin_can_approve_or_return_submitted_sheet(self):
        sheet = self.create_sheet(incoming="0.00")
        sheet.status = DailySheetStatus.SUBMITTED
        sheet.save()
        self.client.force_authenticate(self.super_admin)
        missing_comment = self.client.post(f"/api/daily-sheets/{sheet.id}/return/", {})
        self.assertEqual(missing_comment.status_code, status.HTTP_400_BAD_REQUEST)
        returned = self.client.post(f"/api/daily-sheets/{sheet.id}/return/", {"return_comment": "Fix"})
        self.assertEqual(returned.status_code, status.HTTP_200_OK)
        self.assertEqual(returned.data["return_comment"], "Fix")
        return_log = AuditLog.objects.get(action="SHEET_RETURNED")
        self.assertEqual(return_log.description, "Fix")
        self.assertEqual(return_log.new_values["return_comment"], "Fix")
        sheet.status = DailySheetStatus.SUBMITTED
        sheet.save()
        approved = self.client.post(f"/api/daily-sheets/{sheet.id}/approve/")
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        self.assertEqual(approved.data["status"], DailySheetStatus.APPROVED)

    def test_returned_sheet_can_be_corrected_and_resubmitted(self):
        sheet = self.create_sheet(incoming="0.00")
        self.create_transaction(sheet, self.tpm_one)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.tpm_two, reason="Closed", recorded_by=self.accountant)
        OmittedTerminal.objects.create(daily_sheet=sheet, tpm_code=self.sub_tpm, reason="Closed", recorded_by=self.accountant)
        sheet.status = DailySheetStatus.RETURNED
        sheet.return_comment = "Fix"
        sheet.save()
        self.client.force_authenticate(self.accountant)
        patch = self.client.patch(f"/api/daily-sheets/{sheet.id}/", {"reconciliation_note": ""})
        submit = self.client.post(f"/api/daily-sheets/{sheet.id}/submit/")
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        self.assertEqual(submit.status_code, status.HTTP_200_OK)

    def test_approved_sheets_can_be_reopened_only_by_super_admin(self):
        sheet = self.create_sheet()
        sheet.return_comment = "Earlier return comment"
        sheet.status = DailySheetStatus.APPROVED
        sheet.save()
        self.client.force_authenticate(self.accountant)
        blocked = self.client.post(f"/api/daily-sheets/{sheet.id}/reopen/", {"reopen_reason": "Late issue"})
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.super_admin)
        missing_reason = self.client.post(f"/api/daily-sheets/{sheet.id}/reopen/", {})
        self.assertEqual(missing_reason.status_code, status.HTTP_400_BAD_REQUEST)
        reopened = self.client.post(f"/api/daily-sheets/{sheet.id}/reopen/", {"reopen_reason": "Late issue"})
        self.assertEqual(reopened.status_code, status.HTTP_200_OK)
        self.assertEqual(reopened.data["status"], DailySheetStatus.REOPENED)
        self.assertEqual(reopened.data["return_comment"], "Earlier return comment")
        self.assertEqual(reopened.data["reopen_reason"], "Late issue")
        reopen_log = AuditLog.objects.get(action="SHEET_REOPENED")
        self.assertEqual(reopen_log.description, "Late issue")
        self.assertEqual(reopen_log.new_values["reopen_reason"], "Late issue")

    def test_audit_logs_old_and_new_values_and_visibility(self):
        sheet = self.create_sheet()
        self.client.force_authenticate(self.accountant)
        response = self.client.patch(f"/api/daily-sheets/{sheet.id}/", {"incoming_funds": "1.00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = AuditLog.objects.get(action="INCOMING_FUNDS_CHANGED")
        self.assertEqual(log.old_values["incoming_funds"], "142500.00")
        self.assertEqual(log.new_values["incoming_funds"], "1.00")
        visible = self.client.get("/api/audit-logs/")
        self.assertEqual(visible.status_code, status.HTTP_200_OK)
        self.client.force_authenticate(self.other_accountant)
        hidden = self.client.get("/api/audit-logs/")
        data = hidden.data["results"] if "results" in hidden.data else hidden.data
        self.assertEqual(len(data), 0)
        self.client.force_authenticate(self.super_admin)
        all_logs = self.client.get("/api/audit-logs/")
        data = all_logs.data["results"] if "results" in all_logs.data else all_logs.data
        self.assertGreaterEqual(len(data), 1)

    def test_unauthenticated_requests_are_rejected(self):
        response = self.client.get("/api/daily-sheets/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_filtering_by_agency_status_and_date_range(self):
        sheet = self.create_sheet()
        other = DailySheet.objects.create(agency=self.other_agency, transaction_date=date(2026, 8, 25), created_by=self.super_admin)
        other.copy_weekday_games()
        self.client.force_authenticate(self.super_admin)
        response = self.client.get(
            f"/api/daily-sheets/?agency={self.agency.id}&status={sheet.status}&date_from=2026-08-24&date_to=2026-08-24"
        )
        data = response.data["results"] if "results" in response.data else response.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], sheet.id)

    def test_games_for_date_endpoint(self):
        self.client.force_authenticate(self.accountant)
        response = self.client.get("/api/games/for-date/?date=2026-08-24")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["game_name"] for item in response.data], ["Premier", "Lucky"])
