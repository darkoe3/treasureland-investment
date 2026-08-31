# Treasureland Investment Management System

## Phase 5 Architecture

Phase 4 keeps the existing split architecture:

- Django and Django REST Framework backend in `backend/`.
- Next.js App Router frontend in `frontend/`.
- Browser code calls same-origin `/api/backend/...` BFF routes only.
- The BFF forwards only allowlisted backend paths and methods.
- JWT access and refresh tokens remain in HTTP-only cookies.

The backend remains authoritative for permissions, workflow status and all money calculations.

## Data Models

- `Agency`: Musa 1, Musa 2, Omolade, Treasure Land and Sango are seeded operational agencies.
- `User`: Super Admin or Accountant.
- `UserAgencyAssignment`: links accountants to one or more agencies with independent create, edit, delete, export and view-history flags.
- `Person`: belongs to one agency and may be a main agent or sub-agent.
- `TPMCode`: belongs to one person. A person may have multiple TPM codes. Codes are unique case-insensitively.
- `DailySheet`: one agency/date workflow record.
- `DailySheetGame`: immutable snapshot of games scheduled for the sheet date.
- `TPMDailyTransaction`: one row per TPM code per daily sheet.
- `TransactionGameSale`: per-game sales amounts for a transaction.
- `OmittedTerminal`: active or historical omitted-terminal reason for a sheet.
- `AuditLog`: immutable operational and report history.

## Permission Rules

Super Admin can access and manage all agencies. Accountants can access only assigned agencies. Backend checks are authoritative:

- `can_create`: create people, TPM codes, daily sheets and transaction rows.
- `can_edit`: edit people, TPM codes, editable sheets and omissions.
- `can_delete`: safely deactivate people/TPM codes or remove editable transaction rows.
- `can_view_history`: view audit logs for that agency.
- `can_export`: does not grant Phase 5 report access. Reports and Excel exports are Super Admin-only.

## Daily Sheet Lifecycle

Statuses are `DRAFT`, `SUBMITTED`, `APPROVED`, `RETURNED` and `REOPENED`.

Accountants may edit only assigned-agency sheets in `DRAFT`, `RETURNED` or `REOPENED` status where permission flags allow it. Super Admin alone may approve, return and reopen. Returned comments and reopen reasons are stored separately.

## Calculations

- NET Sales = sum of all game sales for the TPM code.
- Commission = NET Sales x 5%.
- To Pay = NET Sales x 95%.
- Sub-agent share = sub-agent NET Sales x 2%.
- Organisation share on sub-agent sales = sub-agent NET Sales x 3%.
- Manual tax is recorded at agency-sheet level and does not reduce To Pay in Phase 4.
- Difference = actual amount received - calculated agency To Pay.

All backend calculations use `Decimal` with `ROUND_HALF_UP`.

## Phase 5 Reports

Super Admin users can open `/dashboard/reports` and call `GET /api/reports/agency-summary/` or `GET /api/reports/agency-summary/export/`. Accountants receive `403` responses for both preview and export, even when an agency assignment has `can_export=true`. The frontend also hides Reports from accountant navigation, but backend enforcement is authoritative.

Report parameters are `agency`, `period`, period-specific dates and optional repeated `status` values. `period=daily` uses one selected date. `period=weekly` resolves the selected date to Monday through Sunday in `Africa/Accra`. `period=monthly` uses the first through last calendar day, including leap years. `period=custom` uses an inclusive `start_date` and `end_date` and rejects missing or reversed dates.

Official reports default to `APPROVED` sheets only. If any non-approved status is selected, the preview and workbook label the result as an operational/non-final report and show the exact statuses used.

Daily reports use the games snapshotted on the selected sheet. Weekly, monthly and custom reports use the union of snapshotted games from included sheets. Columns are ordered by historical display order, then normalized game name, then stable key. Stable game IDs are used first; if old snapshots ever lack an identity, the documented fallback is a normalized game name. Historical snapshots are not rewritten.

Each detail row represents one TPM Code. A person with multiple TPM Codes appears on multiple adjacent rows; the combined person Total is shown only on the first row to avoid double counting. Final totals sum TPM-level To Pay values, not repeated person Total values.

Excel exports contain workbook metadata, summary metrics, daily reconciliation, detailed TPM/game rows and a totals row. User-controlled text is written as text and prefixed when necessary to prevent spreadsheet formula injection. Filenames and worksheet names are sanitized. Workbooks contain no macros, external links, JWTs, database URLs or internal object IDs.

## API Endpoints

- `GET /api/agencies/`
- `GET|POST /api/people/`
- `GET|PATCH|DELETE /api/people/{id}/`
- `GET|POST /api/tpm-codes/`
- `GET|PATCH|DELETE /api/tpm-codes/{id}/`
- `GET /api/games/for-date/?date=YYYY-MM-DD`
- `GET|POST /api/daily-sheets/`
- `GET|PATCH|DELETE /api/daily-sheets/{id}/`
- `GET /api/daily-sheets/{id}/summary/`
- `POST /api/daily-sheets/{id}/submit/`
- `POST /api/daily-sheets/{id}/approve/`
- `POST /api/daily-sheets/{id}/return/`
- `POST /api/daily-sheets/{id}/reopen/`
- `GET|POST /api/tpm-daily-transactions/`
- `GET|PATCH|DELETE /api/tpm-daily-transactions/{id}/`
- `GET|POST /api/omitted-terminals/`
- `GET|PATCH|DELETE /api/omitted-terminals/{id}/`
- `GET /api/audit-logs/`
- `GET /api/reports/agency-summary/`
- `GET /api/reports/agency-summary/export/`

## Audit Behavior

Important actions create immutable `AuditLog` entries: sheet creation, transaction changes, omitted-terminal changes, workflow actions, accountant assignment changes, person changes, TPM code changes, report previews and report exports. Report audit metadata includes agency, period, resolved dates and statuses, but not report contents.

## Deployment And Migration Notes

Phase 4 adds migration `0005_phase4_tpm_uniqueness_omission_active.py` for active omission history and case-insensitive TPM-code uniqueness. The migration is additive except replacing the old omission uniqueness constraint with an active-only uniqueness constraint. No live Render database operations are required during local development.

## Known Phase 6 Limitations

PDF export, emailed reports, scheduled reports, bulk imports, destructive cleanup and automatic tax deduction remain out of scope. Deployment still uses Render for Django/PostgreSQL and Vercel for Next.js; Phase 5 requires no Render or Vercel setting changes.
