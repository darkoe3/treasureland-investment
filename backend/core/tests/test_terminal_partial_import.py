from io import BytesIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from openpyxl import load_workbook
from rest_framework.test import APITestCase

from core.models import AuditLog, Person, TPMCode, TerminalImportBatch, TerminalNumber
from core.tests.test_phase_4 import Phase4Mixin
from core.tests.test_terminal_register import TerminalRegisterTests, upload


class PartialTerminalImportTests(Phase4Mixin, APITestCase):
    setUp = TerminalRegisterTests.setUp
    data = TerminalRegisterTests.data
    create = TerminalRegisterTests.create

    def preview(self, rows, policy="PARTIAL", mode="ONBOARD_MISSING"):
        result = self.client.post(self.imports + "preview/", {
            "agency": self.musa.pk, "mode": mode, "policy": policy,
            "file": upload(rows)}, format="multipart")
        self.assertEqual(result.status_code, 201, result.data)
        return result.data

    def approve(self, batch, **changes):
        payload = batch["preview_payload"]
        return self.client.post(f"{self.imports}{batch['id']}/confirm/", {
            "confirmed": True, "reason": "Verified source", "warnings_acknowledged": True,
            "acknowledged_counts": payload["creation_counts"], "exclusions_acknowledged": True,
            "expected_valid_count": payload["valid_count"],
            "expected_excluded_count": payload["excluded_count"], **changes}, format="json")

    def counts(self):
        return Person.objects.count(), TPMCode.objects.count(), TerminalNumber.objects.count()

    def test_strict_blocks_partial_imports_and_corrected_remainder_is_idempotent(self):
        rows = [[1, "new", "term", "New Person"], [2, "later", "later-term", None],
                [3, None, None, None]]
        before = self.counts()
        strict = self.preview(rows, policy="STRICT")
        self.assertEqual(self.approve(strict).status_code, 400)
        self.assertEqual(self.counts(), before)
        batch = self.preview(rows)
        self.assertEqual(batch["preview_payload"]["valid_count"], 1)
        self.assertEqual(batch["preview_payload"]["excluded_counts"]["INCOMPLETE"], 1)
        self.assertEqual(batch["preview_payload"]["ignored_blank_rows"], 1)
        result = self.approve(batch)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["result_counts"]["imported"], 1)
        self.assertEqual(result.data["result_counts"]["excluded"], 1)
        self.assertEqual(self.counts(), tuple(n + 1 for n in before))
        self.assertFalse(TPMCode.objects.filter(code="later").exists())
        rows[1][3] = "Later Person"
        corrected = self.preview(rows)
        self.assertEqual(corrected["preview_payload"]["rows"][0]["classification"], "UNCHANGED")
        self.assertEqual(self.approve(corrected).status_code, 200)
        again = self.preview(rows)
        before = self.counts()
        self.assertEqual(self.approve(again).data["result_counts"]["unchanged"], 2)
        self.assertEqual(self.counts(), before)

    def test_name_derivation_requires_selected_agency_assigned_person(self):
        batch = self.preview([[1, self.tpm_a.code, "existing", None],
                              [2, "new", "no-name", None],
                              [3, self.other_tpm.code, "foreign", None]])
        rows = batch["preview_payload"]["rows"]
        self.assertFalse(rows[0]["excluded"])
        self.assertEqual(rows[0]["name"], "")
        self.assertEqual(rows[0]["resolved_name"], self.person.full_name)
        self.assertTrue(all(r["excluded"] for r in rows[1:]))
        before = self.counts()
        self.assertEqual(self.approve(batch).status_code, 200)
        self.assertEqual(self.counts(), (before[0], before[1], before[2] + 1))
        self.assertFalse(Person.objects.filter(full_name="").exists())

    def test_conflicts_excluded_without_changing_existing_records(self):
        terminal = self.create()
        before_people = list(Person.objects.values())
        before_codes = list(TPMCode.objects.values())
        before_terminal = TerminalNumber.objects.values().get(pk=terminal.pk)
        batch = self.preview([[1, "safe", "safe-t", "Safe Person"],
            [2, self.tpm_a.code, "different", "Wrong"],
            [3, self.other_tpm.code, "foreign", self.other_tpm.person.full_name],
            [4, "reassign", terminal.terminal_number, "Other Person"],
            [5, "SAFE", "duplicate-t", "Safe Person"],
            [6, "incomplete", None, "Incomplete Person"], [7, "valid", "valid-t", "Valid Person"]])
        self.assertEqual([r["classification"] for r in batch["preview_payload"]["rows"]][1:],
                         ["NAME_CONFLICT", "AGENCY_CONFLICT", "REASSIGNMENT_REQUIRED", "DUPLICATE", "INCOMPLETE", "CREATE_PERSON_SUBAGENT_TERMINAL"])
        self.assertEqual(batch["preview_payload"]["rows"][0]["classification"], "DUPLICATE")
        self.assertEqual(self.approve(batch).status_code, 200)
        for row in before_people:
            self.assertEqual(Person.objects.values().get(pk=row["id"]), row)
        for row in before_codes:
            self.assertEqual(TPMCode.objects.values().get(pk=row["id"]), row)
        self.assertEqual(TerminalNumber.objects.values().get(pk=terminal.pk), before_terminal)
        self.assertFalse(TPMCode.objects.filter(code__in=["reassign", "incomplete", "safe", "SAFE"]).exists())
        self.assertFalse(Person.objects.filter(full_name__in=["Other Person", "Incomplete Person", "Safe Person"]).exists())

    def test_confirmation_requires_counts_acknowledgements_reason_and_fixed_policy(self):
        batch = self.preview([[1, "new", "term", "New"], [2, "bad", None, None]])
        for changes in ({"expected_valid_count": 2}, {"expected_excluded_count": 0},
                        {"expected_valid_count": None}, {"expected_excluded_count": None},
                        {"expected_valid_count": True}, {"exclusions_acknowledged": False},
                        {"exclusions_acknowledged": "true"}, {"reason": ""},
                        {"acknowledged_counts": {}}, {"confirmed": False}, {"policy": "STRICT"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.approve(batch, **changes).status_code, 400)
        self.assertFalse(TerminalNumber.objects.exists())
        self.assertEqual(self.approve(self.preview([[1, "bad", None, None]])).status_code, 400)

    def test_database_changes_revalidate_excluded_rows_and_counts_under_locks(self):
        batch = self.preview([[1, "safe", "safe-t", "Safe"], [2, "later", "later-t", None]])
        TPMCode.objects.create(code="later", person=self.person)
        self.assertEqual(self.approve(batch).status_code, 400)
        self.assertFalse(TerminalNumber.objects.exists())
        batch = self.preview([[1, "safe", "safe-t", "Safe"]])
        self.create(code=self.other_tpm, terminal_number="safe-t")
        self.assertEqual(self.approve(batch).status_code, 400)
        self.assertFalse(TPMCode.objects.filter(code="safe").exists())

    def test_atomic_subset_rollback_on_second_write(self):
        batch = self.preview([[1, "one", "t1", "One"], [2, "two", "t2", "Two"],
                              [3, "bad", None, "Bad"]])
        before = self.counts()
        audit_count = AuditLog.objects.count()
        from core.terminal_register import create_terminal
        def fail_second(data, user, **kwargs):
            if data["terminal_number"] == "t2":
                raise ValidationError("Forced failure")
            return create_terminal(data, user, **kwargs)
        with patch("core.terminal_register.create_terminal", side_effect=fail_second):
            self.assertEqual(self.approve(batch).status_code, 400)
        self.assertEqual(self.counts(), before)
        self.assertEqual(AuditLog.objects.count(), audit_count)
        self.assertEqual(TerminalImportBatch.objects.get(pk=batch["id"]).status, "PREVIEWED")

    def test_partial_permissions_and_mode(self):
        self.assertEqual(self.client.post(self.imports + "preview/", {
            "agency": self.musa.pk, "policy": "PARTIAL", "mode": "LINK_EXISTING",
            "file": upload([[1, "new", "term", "New"]])}, format="multipart").status_code, 400)
        batch = self.preview([[1, "new", "term", "New"]])
        self.client.force_authenticate(self.acct)
        self.assertEqual(self.approve(batch).status_code, 403)
        self.assertEqual(self.client.get(f"{self.imports}{batch['id']}/exclusions/").status_code, 403)
        self.assertEqual(self.client.post(self.imports + "preview/", {
            "agency": self.musa.pk, "policy": "PARTIAL", "mode": "ONBOARD_MISSING",
            "file": upload([[1, "new", "term", "New"]])}, format="multipart").status_code, 403)

    def test_excel_report_exact_supplied_values_missing_fields_and_metadata_only_audit(self):
        batch = self.preview([[1, None, None, None], [2, "bad", None, None],
                              [3, "=1+1", "formula-t", "Formula"], [4, "safe", "safe-t", "Safe Name"]])
        self.assertEqual(batch["preview_payload"]["rows"][0]["reasons"],
                         ["TERMINAL NOS is required.", "NAME is required."])
        self.assertEqual(self.approve(batch).status_code, 200)
        response = self.client.get(f"{self.imports}{batch['id']}/exclusions/")
        self.assertEqual(response.status_code, 200)
        wb = load_workbook(BytesIO(response.content), data_only=False)
        values = list(wb.active.values)
        self.assertEqual(len(values), 3)
        self.assertEqual(values[1], (3, "bad", None, None, "INCOMPLETE",
                                   "TERMINAL NOS is required. NAME is required."))
        self.assertEqual(values[2][1], "=1+1")
        self.assertEqual(wb.active["B3"].data_type, "s")
        self.assertFalse(AuditLog.objects.filter(action="TERMINAL_CREATED").exists())
        log = AuditLog.objects.get(action="TERMINAL_IMPORT_CONFIRMED")
        self.assertEqual(log.new_values["policy"], "PARTIAL")
        self.assertEqual(log.new_values["imported_count"], 1)
        for text in ("Safe Name", "safe-t", "formula-t", "register.xlsx", "file_hash", "source_rows"):
            self.assertNotIn(text, str(log.new_values))

    def test_all_duplicate_occurrences_are_excluded_instead_of_selecting_first_owner(self):
        before = self.counts()
        batch = self.preview([[1, "one", "shared", "One"], [2, "two", "SHARED", "Two"],
                              [3, "safe", "safe-t", "Safe"]])
        self.assertEqual([r["classification"] for r in batch["preview_payload"]["rows"]][:2],
                         ["DUPLICATE", "DUPLICATE"])
        self.assertEqual(batch["preview_payload"]["creation_counts"]["people"], 1)
        self.assertEqual(self.approve(batch).status_code, 200)
        self.assertEqual(self.counts(), tuple(n + 1 for n in before))
        self.assertFalse(Person.objects.filter(full_name__in=["One", "Two"]).exists())
        self.assertFalse(TerminalNumber.objects.filter(terminal_number__iexact="shared").exists())

    def test_derived_owner_changes_and_blank_only_batches_cannot_confirm(self):
        blank = self.preview([[1, None, None, None]])
        self.assertEqual(self.approve(blank).status_code, 400)
        batch = self.preview([[1, self.tpm_a.code, "derived", None]])
        self.person.full_name = "Changed name"
        self.person.save()
        self.assertEqual(self.approve(batch).status_code, 400)
        self.assertFalse(TerminalNumber.objects.exists())
