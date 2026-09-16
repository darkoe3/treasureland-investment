from datetime import date, timedelta
from io import BytesIO, StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APITestCase

from core.importers import parse_daily_sheet_workbook
from core.models import AuditLog, TerminalImportBatch, TerminalNumber, TPMCode, TPMDailyTransaction, User
from core.tests.test_daily_sheet_imports import workbook_upload
from core.tests.test_phase_4 import Phase4Mixin


def upload(rows):
    wb = Workbook()
    wb.active.append(["S/NOS", "SUB AGT NOS", "TERMINAL NOS", "NAME"])
    for row in rows:
        wb.active.append(row)
    stream = BytesIO()
    wb.save(stream)
    return SimpleUploadedFile("register.xlsx", stream.getvalue())


class TerminalRegisterTests(Phase4Mixin, APITestCase):
    def setUp(self):
        self.setUpBase()
        self.client.force_authenticate(self.admin)
        self.base = "/api/terminal-numbers/"
        self.imports = "/api/terminal-number-imports/"

    def data(self, code=None, **kwargs):
        code = code or self.tpm_a
        return {"agency": code.person.agency_id, "person": code.person_id,
                "sub_agent_number": code.pk, "terminal_number": "00123", **kwargs}

    def create(self, **kwargs):
        response = self.client.post(self.base, self.data(**kwargs), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return TerminalNumber.objects.get(pk=response.data["id"])

    def preview(self, rows=None):
        response = self.client.post(self.imports + "preview/", {"agency": self.musa.pk,
            "file": upload(rows if rows is not None else [[1, self.tpm_a.code, "00009", "  ayo  "]])}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def confirm(self, batch):
        return self.client.post(f"{self.imports}{batch['id']}/confirm/", {"confirmed": True}, format="json")

    def reassign(self, terminal, code=None, **kwargs):
        return self.client.post(f"{self.base}{terminal.pk}/reassign/",
            self.data(code=code or self.tpm_sub, reason="Replacement allocation", confirmed=True, **kwargs), format="json")

    def test_manual_text_leading_zeroes_relationships_and_audit(self):
        terminal = self.create(terminal_number=" 001Ab ")
        self.assertEqual(terminal.terminal_number, "001Ab")
        self.assertEqual(terminal.person_id, self.tpm_a.person_id)
        self.assertEqual(AuditLog.objects.get(action="TERMINAL_CREATED").new_values["terminal_number"], "001Ab")
        self.assertEqual(TPMCode.objects.get(pk=self.tpm_a.pk).code, "TPM-A")
        for bad in (123, True, " ", "x" * 81):
            self.assertEqual(self.client.post(self.base, self.data(code=self.tpm_b, terminal_number=bad), format="json").status_code, 400)

    def test_relationship_mismatch(self):
        for attrs in ({"agency": self.sango.pk}, {"person": self.sub.pk}, {"sub_agent_number": 999999}):
            response = self.client.post(self.base, self.data(**attrs), format="json")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(TerminalNumber.objects.exists())

    def test_uniqueness_and_inactive_identifier_reservation(self):
        terminal = self.create(terminal_number="00Ab")
        self.assertEqual(self.client.post(self.base, self.data(code=self.tpm_b, terminal_number="00aB"), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.base, self.data(terminal_number="other"), format="json").status_code, 400)
        self.client.post(f"{self.base}{terminal.pk}/deactivate/")
        self.assertEqual(self.client.post(self.base, self.data(code=self.tpm_b, terminal_number="00AB"), format="json").status_code, 400)
        self.create(terminal_number="different")
        self.assertEqual(self.client.post(f"{self.base}{terminal.pk}/reactivate/").status_code, 400)

    def test_deactivate_reactivate_and_edit_history(self):
        terminal = self.create()
        url = f"{self.base}{terminal.pk}/"
        self.assertEqual(self.client.patch(url, {"terminal_number": "000456"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"person": self.sub.pk}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url + "deactivate/").status_code, 200)
        terminal.refresh_from_db()
        self.assertEqual(terminal.deactivated_by, self.admin)
        self.assertIsNotNone(terminal.deactivated_at)
        self.assertEqual(self.client.post(url + "reactivate/").status_code, 200)
        terminal.refresh_from_db()
        self.assertIsNone(terminal.deactivated_at)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertEqual(len(self.client.get(url + "history/").data), 4)

    def test_accountant_isolation_and_write_restrictions(self):
        own = self.create()
        hidden = self.create(code=self.other_tpm, terminal_number="hidden")
        self.client.force_authenticate(self.acct)
        self.assertEqual([r["id"] for r in self.client.get(self.base).data], [own.id])
        self.assertEqual(self.client.get(f"{self.base}{hidden.pk}/").status_code, 404)
        self.assertEqual(self.client.get(self.base + f"?agency={self.sango.pk}").data, [])
        for action in ("deactivate", "reactivate", "reassign"):
            self.assertEqual(self.client.post(f"{self.base}{own.pk}/{action}/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.post(self.base, self.data(), format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{self.base}{own.pk}/", {"terminal_number": "new"}).status_code, 403)
        self.assertEqual(self.client.post(self.imports + "preview/", {}).status_code, 403)
        self.assertEqual(self.client.get(f"{self.base}{own.pk}/history/").status_code, 403)

    def test_reassignment_requires_confirmation_reason_and_target(self):
        terminal = self.create()
        for changes in ({"confirmed": False}, {"reason": " "}, {"agency": self.sango.pk}):
            data = {**self.data(code=self.tpm_sub), "reason": "reason", "confirmed": True, **changes}
            self.assertEqual(self.client.post(f"{self.base}{terminal.pk}/reassign/", data, format="json").status_code, 400)
        self.create(code=self.tpm_sub, terminal_number="occupied")
        self.assertEqual(self.reassign(terminal).status_code, 400)

    def test_cross_agency_reassignment_snapshots_and_immutable_history(self):
        terminal = self.create()
        txn = self.txn(self.sheet(), self.tpm_a)
        before = (txn.person_name_snapshot, txn.tpm_code_snapshot, txn.terminal_number_snapshot)
        self.assertEqual(before[-1], "00123")
        self.assertEqual(self.reassign(terminal, self.other_tpm).status_code, 200)
        txn.refresh_from_db()
        self.assertEqual(before, (txn.person_name_snapshot, txn.tpm_code_snapshot, txn.terminal_number_snapshot))
        log = AuditLog.objects.get(action="TERMINAL_REASSIGNED")
        self.assertEqual(log.old_values["agency"], self.musa.pk)
        self.assertEqual(log.new_values["agency"], self.sango.pk)
        for action in (lambda: log.save(), lambda: log.delete(), lambda: AuditLog.objects.filter(pk=log.pk).update(description="rewrite"), lambda: AuditLog.objects.filter(pk=log.pk).delete()):
            with self.assertRaises(ValidationError):
                action()
        self.client.force_authenticate(self.acct)
        self.assertEqual(self.client.get(f"{self.base}{terminal.pk}/").status_code, 404)

    def test_indirect_owner_changes_are_blocked(self):
        self.create()
        self.assertEqual(self.client.patch(f"/api/tpm-codes/{self.tpm_a.pk}/", {"person": self.sub.pk, "confirm_reassignment": True}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"/api/people/{self.person.pk}/", {"agency": self.sango.pk}, format="json").status_code, 400)

    def test_template_text_no_formulas_and_round_trip(self):
        response = self.client.get(self.imports + f"template/?agency={self.musa.pk}")
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(BytesIO(response.content))
        self.assertEqual([c.value for c in wb.active[1]], ["S/NOS", "SUB AGT NOS", "TERMINAL NOS", "NAME"])
        self.assertEqual(wb.active["B2"].number_format, "@")
        self.assertEqual(wb.active["C2"].number_format, "@")
        wb.active["B2"], wb.active["C2"], wb.active["D2"] = self.tpm_a.code, "000099", self.person.full_name
        for sheet in wb:
            self.assertFalse(any(c.data_type == "f" for row in sheet for c in row))
        stream = BytesIO(); wb.save(stream)
        preview = self.client.post(self.imports + "preview/", {"agency": self.musa.pk, "file": SimpleUploadedFile("template.xlsx", stream.getvalue())}, format="multipart")
        self.assertEqual(preview.data["warnings"], [])
        self.assertEqual(preview.data["errors"], [])
        self.assertEqual(self.confirm(preview.data).status_code, 200)
        self.assertEqual(TerminalNumber.objects.get().terminal_number, "000099")

    def test_preview_has_no_terminal_writes_then_atomic_confirm(self):
        batch = self.preview()
        self.assertFalse(TerminalNumber.objects.exists())
        self.assertEqual(batch["preview_payload"]["rows"][0]["classification"], "New")
        self.assertEqual(self.confirm(batch).status_code, 200)
        self.assertEqual(TerminalNumber.objects.get().terminal_number, "00009")
        self.assertEqual(self.confirm(batch).status_code, 400)
        batch = self.preview()
        self.assertEqual(batch["preview_payload"]["rows"][0]["classification"], "Unchanged")
        self.assertEqual(self.confirm(batch).data["result_counts"], {"created": 0, "unchanged": 1})
        log = AuditLog.objects.filter(action="TERMINAL_IMPORT_PREVIEWED").first()
        self.assertNotIn("rows", log.new_values)

    def test_preview_duplicates_formulas_names_partial_rows_and_numeric_warning(self):
        rows = [[1, self.tpm_a.code, "0001", "Ayo"], [2, self.tpm_a.code.lower(), "0001", "wrong"],
                [3, self.tpm_b.code, None, "Ayo"], [4, "=1+1", "1", "Ayo"],
                [5, 123, 123, "Ayo"], [None, None, None, None]]
        batch = self.preview(rows)
        messages = " ".join(e["message"] for e in batch["errors"])
        for text in ("Row 3", "Duplicate", "NAME", "required", "Formula", "does not exist"):
            self.assertIn(text, messages)
        self.assertTrue(batch["warnings"])
        self.assertEqual(len(batch["preview_payload"]["rows"]), 5)
        self.assertEqual(self.confirm(batch).status_code, 400)

    def test_conflict_classification_and_no_overwrite(self):
        terminal = self.create()
        batch = self.preview([[1, self.tpm_b.code, terminal.terminal_number, "Ayo"]])
        self.assertEqual(batch["preview_payload"]["rows"][0]["classification"], "Reassignment required")
        batch = self.preview([[1, self.tpm_a.code, "other", "Ayo"]])
        self.assertEqual(batch["preview_payload"]["rows"][0]["classification"], "Conflict")
        self.client.post(f"{self.base}{terminal.pk}/deactivate/")
        batch = self.preview([[1, self.tpm_a.code, terminal.terminal_number, "Ayo"]])
        self.assertEqual(batch["preview_payload"]["rows"][0]["classification"], "Update required")

    def test_confirm_rolls_back_first_row_when_second_row_changed(self):
        batch = self.preview([[1, self.tpm_a.code, "new1", "Ayo"], [2, self.tpm_b.code, "new2", "Ayo"]])
        self.create(code=self.tpm_sub, terminal_number="new2")
        self.assertEqual(self.confirm(batch).status_code, 400)
        self.assertFalse(TerminalNumber.objects.filter(terminal_number="new1").exists())
        self.assertEqual(TerminalImportBatch.objects.get(pk=batch["id"]).status, "PREVIEWED")

    def test_batch_ownership_expiry_cancel_and_confirmation(self):
        batch = self.preview()
        other_admin = User.objects.create_superuser("other-admin@example.com", "AdminPass456!", full_name="Other admin")
        self.client.force_authenticate(other_admin)
        self.assertEqual(self.confirm(batch).status_code, 404)
        self.assertEqual(self.client.get(f"{self.imports}{batch['id']}/").status_code, 404)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f"{self.imports}{batch['id']}/confirm/", {}).status_code, 400)
        self.assertEqual(self.client.post(f"{self.imports}{batch['id']}/cancel/").status_code, 200)
        self.assertEqual(self.confirm(batch).status_code, 400)
        self.assertTrue(AuditLog.objects.filter(action="TERMINAL_IMPORT_CANCELLED").exists())
        batch = self.preview()
        TerminalImportBatch.objects.filter(pk=batch["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.confirm(batch).status_code, 400)

    def test_failed_audit_rolls_back_terminal(self):
        with patch("core.terminal_register.audit", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.base, self.data(), format="json")
        self.assertFalse(TerminalNumber.objects.exists())

    def test_daily_import_system_mapping_and_conflict(self):
        self.create()
        def parse(register):
            return parse_daily_sheet_workbook(workbook_upload(rows=[{"sub": self.tpm_a.code, "amounts": [10, 20]}], headers=["Premier", "Lucky"], register_rows=register, raw_date=date(2026, 8, 24)), self.musa, date(2026, 8, 24))
        result = parse([(self.tpm_a.code, "00123", "Ayo")])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.payload["rows"][0]["terminal_number"], "00123")
        self.assertEqual(parse([]).errors, [])
        self.assertTrue(parse([(self.tpm_a.code, "wrong", "Ayo")]).errors)
        self.assertTrue(parse([(self.tpm_a.code, "00123", "wrong")]).errors)

    def test_report_reads_snapshot_and_blank_not_current_assignment(self):
        sheet = self.sheet()
        old = self.txn(sheet, self.tpm_a)
        terminal = self.create()
        self.txn(sheet, self.tpm_b)
        self.reassign(terminal, self.other_tpm)
        response = self.client.get(f"/api/reports/agency-summary/?agency={self.musa.pk}&period=daily&date=2026-08-24&status=DRAFT")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(all(row["terminal_number"] == "Not recorded" for row in response.data["details"]))
        old.refresh_from_db()
        self.assertEqual(old.terminal_number_snapshot, "")

    def test_readiness_command_is_read_only(self):
        self.txn(self.sheet(), self.tpm_a)
        output = StringIO()
        call_command("terminal_readiness", stdout=output)
        self.assertIn('"historical_transactions_without_terminal_snapshot": 1', output.getvalue())
        self.assertFalse(TerminalNumber.objects.exists())
        self.assertEqual(TPMDailyTransaction.objects.count(), 1)
