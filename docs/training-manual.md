# Treasureland Training Manual

## Super Admin

Use the dashboard to review all agencies, manage accountants, maintain people and Sub-Agent Numbers, and approve, return or reopen submitted sheets.

## Accountant

Accountants see only assigned agencies. Available actions depend on the permissions granted by Super Admin.

## Creating People And Sub-Agent Numbers

Open `People & Sub-Agent Numbers`. Create a person with agency, name and main-agent or sub-agent status. Add one or more Sub-Agent Numbers to the person. Duplicate Sub-Agent Numbers are rejected even when letter case differs.

Screenshot placeholder: People list and person form.

## Creating A Daily Sheet

Open `Daily Sheets`, choose an accessible agency and date, then create the sheet. The system copies that date's games into the sheet.

Screenshot placeholder: Daily sheet creation.

## Entering Game Sales

Open a sheet, search by name or Sub-Agent Number, select the terminal, then enter sales for every game shown. Zero is allowed. Negative values are rejected. Save each row before moving to another terminal.

Screenshot placeholder: Transaction entry.

## Importing Game Sales From Excel

Open `Daily Sheets`, then choose `Upload Excel`. Select the authorised agency, transaction date and one `.xlsx` workbook. The workbook must use the approved five-sheet format: `ENTER GAME DATA HERE`, `REGISTER SUB-AGENT`, `MUSA RESULTS`, `Premier Games` and `Sheet2`.

The importer reads raw sales from `ENTER GAME DATA HERE`. Use rows 5 through 224 only. `SUB AGT NOS` in column B matches the existing Sub-Agent Number. The system Terminal Number register supplies its terminal; `REGISTER SUB-AGENT` is checked for conflicts. Older column-C mappings remain supported with a legacy warning only until a conflicting system mapping exists. Row 3 supplies the game names for columns C through I.

Choose `Preview upload` before anything is saved. Review the agency, date, file name, row count, ignored blank or zero rows, Sub-Agent Number, system person name, workbook name, game amounts, NET Sales, To Pay, warnings and blocking errors. Warnings should be checked, but blocking errors must be corrected before import can be confirmed.

If the workbook date differs from the selected date, tick the acknowledgement only when the selected date is the correct business date. If an editable Draft already contains transaction rows, tick the replacement checkbox only when those rows should be replaced by the upload. Submitted and Approved sheets cannot be overwritten.

Choose `Confirm Import` to create or update the Draft sheet, then review the normal daily-sheet detail page before submitting. Manual transaction entry remains available when a workbook is not used.

Screenshot placeholder: Excel import upload.
Screenshot placeholder: Excel import preview.

## Marking Omitted Terminals

The sheet shows expected active terminals that have not been entered. Choose `Mark omitted`, enter a reason, and save. A terminal cannot have both a transaction and an active omitted record.

Screenshot placeholder: Omitted terminals.

## Tax And Actual Amount Received

Enter manual tax and actual amount received in the agency daily total section. Tax is recorded only; it does not reduce To Pay in Phase 4.

## Understanding Totals

NET Sales is the sum of game sales. Commission is 5%. To Pay is 95%. For sub-agents, the 5% commission is split into 2% sub-agent share and 3% organisation share. Difference is actual amount received minus To Pay.

## Submit, Return, Approve And Reopen

Accountants submit draft, returned or reopened sheets after all terminals are entered or omitted. Super Admin may approve submitted sheets, return submitted sheets with a comment, or reopen approved sheets with a reason.

Screenshot placeholder: Super Admin review actions.

## Reports And Excel Export

Reports are available to Super Admin users only. Open `Reports` from the dashboard sidebar, choose one agency, then choose Daily, Weekly, Monthly or Custom range.

Daily reports use the selected date. Weekly reports use the Monday through Sunday week containing the selected date. Monthly reports use the first through last day of the selected month. Custom reports use the exact inclusive start and end dates you choose; if the start date is after the end date the system asks you to correct it.

Reports default to Approved sheets. This is the official report view. If you include Draft, Submitted, Returned or Reopened sheets, the screen and Excel file are labelled operational/non-final. Use operational reports for checking work in progress, not final financial reporting.

After selecting filters, choose `Generate report` to preview the report. Summary cards show daily sheet count, transaction rows, distinct people, distinct Sub-Agent Numbers, NET Sales, commission, To Pay, sub-agent share, organisation share, manual tax, actual received, difference and omitted terminals. Positive, zero and negative differences are styled separately.

The Daily Reconciliation table shows one row per included sheet. Use it to compare calculated To Pay against the actual amount received and identify dates with a shortfall or excess.

The Detailed Sub-Agent/Game Summary keeps each Sub-Agent Number as its own row. If one person has more than one Sub-Agent Number, the Total for that person appears only on the first Sub-Agent row so it is not counted twice. Wide game tables scroll horizontally inside the table area.

Choose `Download Excel` to save an `.xlsx` workbook for the same agency, date range and statuses shown on screen. Protect exported files as financial records: store them in an approved location and do not email or share them outside company policy.

If a report is empty, confirm the agency, date range and status filter. Approved-only reports are empty when matching sheets have not yet been approved.

Screenshot placeholder: Reports filters.
Screenshot placeholder: Approved report preview.
Screenshot placeholder: Operational/non-final status warning.
Screenshot placeholder: Excel workbook opened in spreadsheet software.

## Common Validation Messages

- `A daily sheet already exists for that agency and date.`
- `Sale amount cannot be negative.`
- `Only .xlsx files are supported.`
- `Game {name} is not scheduled for the selected date.`
- `Sales row is missing SUB AGT NOS.`
- `TERMINAL NOS {code} does not match a system Sub-Agent Number.`
- `Set replace_existing=true to replace existing transactions.`
- `Every active Sub-Agent Number must be entered or omitted with an explanation.`
- `A Sub-Agent Number cannot be both entered and omitted.`
- `This sheet is locked against changes.`
- `Return comment is required.`
- `A reopen reason is required.`

## Safe Logout And Password Practices

Use the dashboard logout button when leaving a shared device. Do not share passwords. Super Admin should reset an accountant password if compromise is suspected.

## Managing Terminal Numbers

Existing numbers in People & Sub-Agent Numbers are SUB AGT NOS. Do not recreate them. Open **Terminal Numbers** to search by terminal, Sub-Agent Number or name and filter by agency/status. Accountants can view their agencies; a Super Admin manages assignments.

To add a terminal, select Agency, then Person, then the existing Sub-Agent Number. Enter the Terminal Number exactly, including leading zeroes, choose status and save. Edit changes only terminal text. Deactivate keeps the record/history. Reactivate succeeds only if its Sub-Agent Number has no other active terminal.

For reassignment, choose **Reassign**, select the target agency/person/Sub-Agent Number, enter a reason, review both old and new agencies, tick confirmation and submit. An occupied target requires explicit deactivation of its current terminal first. Reassignment retains active/inactive status. **View history** shows previous and new assignment details, time and actor. Past transactions retain their original names and numbers.

For Excel entry, choose **Upload Excel**, select agency, and **Download template**. Keep the first row unchanged: A S/NOS, B SUB AGT NOS, C TERMINAL NOS, D NAME. Start on row 2. S/NOS is ignored. B and C must be text; NAME must match the existing database person, ignoring case and harmless whitespace. Do not add formulas or create new people through this workbook.

Choose **Preview upload** and read each row?s messages. Numeric identifier warnings mean zeroes may already have been lost: correct the spreadsheet before proceeding if necessary. Blank rows are ignored; partially completed rows block import. New rows are created only on confirmation and Unchanged rows are skipped. Update required, Reassignment required and Conflict rows must be resolved with the manual actions, followed by a fresh preview. There is no silent replacement.

Tick the review checkbox and **Confirm import** only when there are no blocking errors. The whole batch succeeds or rolls back. Previews expire after one hour and can be confirmed only by their uploader. **Cancel import** records cancellation.

Daily sheets now display both Sub-Agent Number and Terminal Number. **Not recorded** means no terminal snapshot was captured for that historical transaction; it does not mean the current register lacks an assignment. For daily workbooks, use the system Sub-Agent Number in SUB AGT NOS. A legacy compatibility warning identifies an older column-C mapping; a system-register conflict must be corrected before import.

## Payments

Open **Payments** from the dashboard. Payments are independent of Daily Sheets and do not come from daily-sheet sales.

### Payers and Sub-Agent Numbers

Open **Payers** and choose an agency-scoped payer. Super Admin can add, edit, activate or deactivate payers. Accountants need the matching agency permission. Open a payer to link or unlink active existing Sub-Agent Numbers from the same agency. Reassignment requires selecting a new same-agency payer and confirming the previous and new payer. Reassignment does not change historical receipts or snapshots.

### Obligations and receipts

Create an obligation with its agency, payer, description, obligation date and positive expected amount. An obligation can receive several full or partial payments until its balance reaches zero. Open an obligation to see expected, posted, reversed and outstanding amounts and its receipt history. Cancel an unpaid obligation with a required reason. Paid and cancelled obligations do not offer payment controls. Do not look for Edit or Delete on posted payments; corrections use a Super Admin reversal and a new payment.

### Record a payment

Choose **Record payment** on an open obligation. Confirm the payer, agency, obligation number, expected amount, amount already paid, remaining balance, amount received, method, reference when required and optional note. Submit once and wait for the result. The browser protects a retry of the same unchanged attempt with one secure idempotency key; changing the material form values creates a new attempt. On success, note the receipt number and use **Download receipt**. The backend is authoritative if the balance changed while the form was open.

Only Super Admin can reverse a posted payment. Reversal requires a prominent confirmation and a reason. A reversed payment remains in history and its PDF remains downloadable, but it is not included in active posted collections.

### Payment analytics

**Analytics** separates the obligation portfolio from collections. Obligation date filters apply to expected/outstanding obligations; payment date filters apply to receipts, and both ranges are inclusive. Read Gross posted, Reversed, Net collected and Outstanding separately. Review status counts, payment-method totals, daily/monthly trends and the Super Admin agency breakdown. The collection rate is zero when expected value is zero. No Teller/Cashier workflow is available.

### Payment UAT checklist

- Confirm an Accountant cannot see or open another agency's payer, obligation, payment or receipt by changing filters or IDs.
- Create a payer, link/unlink a same-agency Sub-Agent Number, and complete a confirmed reassignment without changing an old receipt.
- Create an obligation, post two partial payments, retry one request, and confirm one receipt per successful payment.
- Confirm overpayment, missing references, invalid dates and cancelled/paid-obligation attempts show safe field errors.
- Confirm posted payments have no edit/delete controls and only Super Admin sees reversal.
- Reverse a receipt, download its PDF, and confirm active collection totals exclude the reversed amount.
- Compare inclusive date boundaries, status counts, method breakdowns and zero-expected analytics.
