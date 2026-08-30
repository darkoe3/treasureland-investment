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

## Common Validation Messages

- `A daily sheet already exists for that agency and date.`
- `Sale amount cannot be negative.`
- `Every active TPM code must be entered or omitted with an explanation.`
- `A TPM code cannot be both entered and omitted.`
- `This sheet is locked against changes.`
- `Return comment is required.`
- `A reopen reason is required.`

## Safe Logout And Password Practices

Use the dashboard logout button when leaving a shared device. Do not share passwords. Super Admin should reset an accountant password if compromise is suspected.
