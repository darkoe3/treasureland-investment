# Treasureland Training Manual

## Super Admin

Use the dashboard to review all agencies, manage accountants, maintain people and TPM codes, and approve, return or reopen submitted sheets.

## Accountant

Accountants see only assigned agencies. Available actions depend on the permissions granted by Super Admin.

## Creating People And TPM Codes

Open `People & TPM Codes`. Create a person with agency, name and main-agent or sub-agent status. Add one or more TPM codes to the person. Duplicate TPM codes are rejected even when letter case differs.

Screenshot placeholder: People list and person form.

## Creating A Daily Sheet

Open `Daily Sheets`, choose an accessible agency and date, then create the sheet. The system copies that date's games into the sheet.

Screenshot placeholder: Daily sheet creation.

## Entering Game Sales

Open a sheet, search by name or TPM code, select the terminal, then enter sales for every game shown. Zero is allowed. Negative values are rejected. Save each row before moving to another terminal.

Screenshot placeholder: Transaction entry.

## Importing Game Sales From Excel

Open `Daily Sheets`, then choose `Upload Excel`. Select the authorised agency, transaction date and one `.xlsx` workbook. The workbook must use the approved five-sheet format: `ENTER GAME DATA HERE`, `REGISTER SUB-AGENT`, `MUSA RESULTS`, `Premier Games` and `Sheet2`.

The importer reads raw sales from `ENTER GAME DATA HERE`. Use rows 5 through 224 only. `SUB AGT NOS` in column B is matched through `REGISTER SUB-AGENT` to `TERMINAL NOS`, which is the system TPM Code. Row 3 supplies the game names for columns C through I.

Choose `Preview upload` before anything is saved. Review the agency, date, file name, row count, ignored blank or zero rows, TPM Code, system person name, workbook name, game amounts, NET Sales, To Pay, warnings and blocking errors. Warnings should be checked, but blocking errors must be corrected before import can be confirmed.

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

After selecting filters, choose `Generate report` to preview the report. Summary cards show daily sheet count, transaction rows, distinct people, distinct TPM Codes, NET Sales, commission, To Pay, sub-agent share, organisation share, manual tax, actual received, difference and omitted terminals. Positive, zero and negative differences are styled separately.

The Daily Reconciliation table shows one row per included sheet. Use it to compare calculated To Pay against the actual amount received and identify dates with a shortfall or excess.

The Detailed TPM/Game Summary keeps each TPM Code as its own row. If one person has more than one TPM Code, the Total for that person appears only on the first TPM row so it is not counted twice. Wide game tables scroll horizontally inside the table area.

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
- `TERMINAL NOS {code} does not match a system TPM code.`
- `Set replace_existing=true to replace existing transactions.`
- `Every active TPM code must be entered or omitted with an explanation.`
- `A TPM code cannot be both entered and omitted.`
- `This sheet is locked against changes.`
- `Return comment is required.`
- `A reopen reason is required.`

## Safe Logout And Password Practices

Use the dashboard logout button when leaving a shared device. Do not share passwords. Super Admin should reset an accountant password if compromise is suspected.
