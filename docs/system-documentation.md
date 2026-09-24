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
- `TPMCode`: belongs to one person. A person may have multiple Sub-Agent Numbers. Codes are unique case-insensitively.
- `DailySheet`: one agency/date workflow record.
- `DailySheetGame`: immutable snapshot of games scheduled for the sheet date.
- `TPMDailyTransaction`: one row per Sub-Agent Number per daily sheet.
- `TransactionGameSale`: per-game sales amounts for a transaction.
- `DailySheetImportBatch`: server-side Excel-import preview state containing safe metadata, normalized rows and warning/error summaries; it does not store the raw workbook.
- `OmittedTerminal`: active or historical omitted-terminal reason for a sheet.
- `AuditLog`: immutable operational and report history.

## Permission Rules

Super Admin can access and manage all agencies. Accountants can access only assigned agencies. Backend checks are authoritative:

- `can_create`: create people, Sub-Agent Numbers, daily sheets and transaction rows.
- `can_edit`: edit people, Sub-Agent Numbers, editable sheets and omissions.
- `can_delete`: safely deactivate people/Sub-Agent Numbers or remove editable transaction rows.
- `can_view_history`: view audit logs for that agency.
- `can_export`: does not grant Phase 5 report access. Reports and Excel exports are Super Admin-only.

## Daily Sheet Lifecycle

Statuses are `DRAFT`, `SUBMITTED`, `APPROVED`, `RETURNED` and `REOPENED`.

Accountants may edit only assigned-agency sheets in `DRAFT`, `RETURNED` or `REOPENED` status where permission flags allow it. Super Admin alone may approve, return and reopen. Returned comments and reopen reasons are stored separately.

Excel import is an alternate way to populate an editable daily sheet. It never overwrites Submitted or Approved sheets. If an editable Draft already contains transaction rows, confirmation must explicitly replace the existing rows; imports do not silently merge. Creating a sheet by import snapshots the current active weekday games, including Whole Day entries. Later schedule edits do not rewrite historical `DailySheetGame` snapshots.

## Calculations

- NET Sales = sum of all game sales for the Sub-Agent Number.
- Commission = NET Sales x 5%.
- To Pay = NET Sales x 95%.
- Sub-agent share = sub-agent NET Sales x 2%.
- Organisation share on sub-agent sales = sub-agent NET Sales x 3%.
- Manual tax is recorded at agency-sheet level and does not reduce To Pay in Phase 4.
- Difference = actual amount received - calculated agency To Pay.

All backend calculations use `Decimal` with `ROUND_HALF_UP`.

## Daily Sheet Excel Import

All five agencies use the same workbook structure as `MUSA Sales Summary Sheet Calculator.xlsx`. The backend imports only `ENTER GAME DATA HERE`: `B2` is the advisory workbook date, `B5:B224` is `SUB AGT NOS`, row 3 supplies game headers, and `C:I` contain raw game-sales amounts. `SUB AGT NOS` matches existing `TPMCode.code`; `TERMINAL NOS` is compared with the separate Terminal Number register. Legacy column-C resolution is allowed only without conflicting system registration and produces a visible warning. `MUSA RESULTS`, `Premier Games` and `Sheet2` are recognized but not used as authoritative payment data.

Game headers are trimmed, matched case-insensitively and normalized through approved aliases such as `F/chance` to `Fairchance`, `Inter` to `International`, `MK II` to `Mark II`, `c/master` to `Club Master`, `o6` to `06` and `msp` to `Monday Special`. Every nonblank sales header must match a `DailySheetGame` snapshot for the selected date. Blank optional H/I headers are ignored only when they have no sales values.

Preview validates workbook structure, file signature, size, sheet count, row/column limits, macro/external-link/embedded-content absence, identifiers, duplicate rows, formulas in sales cells, negative or invalid money values, selected-date mismatch and existing-sheet replacement state. Blocking errors disable confirmation. Warnings include blank/zero ignored rows, workbook/system name differences and numeric identifiers that may have lost leading zeroes.

Confirmation uses the server-side `DailySheetImportBatch` and writes atomically. Django recalculates all transaction totals, commission, To Pay, shares, tax and differences from imported raw sales. The workbook's legacy formulas and cached totals are advisory only.

## Phase 5 Reports

Super Admin users can open `/dashboard/reports` and call `GET /api/reports/agency-summary/` or `GET /api/reports/agency-summary/export/`. Accountants receive `403` responses for both preview and export, even when an agency assignment has `can_export=true`. The frontend also hides Reports from accountant navigation, but backend enforcement is authoritative.

Report parameters are `agency`, `period`, period-specific dates and optional repeated `status` values. `period=daily` uses one selected date. `period=weekly` resolves the selected date to Monday through Sunday in `Africa/Accra`. `period=monthly` uses the first through last calendar day, including leap years. `period=custom` uses an inclusive `start_date` and `end_date` and rejects missing or reversed dates.

Official reports default to `APPROVED` sheets only. If any non-approved status is selected, the preview and workbook label the result as an operational/non-final report and show the exact statuses used.

Daily reports use the games snapshotted on the selected sheet. Weekly, monthly and custom reports use the union of snapshotted games from included sheets. Columns are ordered by historical display order, then normalized game name, then stable key. Stable game IDs are used first; if old snapshots ever lack an identity, the documented fallback is a normalized game name. Historical snapshots are not rewritten.

Each detail row represents one Sub-Agent Number. A person with multiple Sub-Agent Numbers appears on multiple adjacent rows; the combined person Total is shown only on the first row to avoid double counting. Final totals sum TPM-level To Pay values, not repeated person Total values.

Excel exports contain workbook metadata, summary metrics, daily reconciliation, detailed TPM/game rows and a totals row. User-controlled text is written as text and prefixed when necessary to prevent spreadsheet formula injection. Filenames and worksheet names are sanitized. Workbooks contain no macros, external links, JWTs, database URLs or internal object IDs.

## API Endpoints

- `GET /api/agencies/`
- `GET|POST /api/people/`
- `GET|PATCH|DELETE /api/people/{id}/`
- `GET|POST /api/tpm-codes/`
- `GET|PATCH|DELETE /api/tpm-codes/{id}/`
- `GET /api/games/for-date/?date=YYYY-MM-DD`
- `POST /api/daily-sheet-imports/preview/`
- `GET /api/daily-sheet-imports/{id}/`
- `POST /api/daily-sheet-imports/{id}/confirm/`
- `POST /api/daily-sheet-imports/{id}/cancel/`
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

Important actions create immutable `AuditLog` entries: sheet creation, transaction changes, omitted-terminal changes, workflow actions, accountant assignment changes, person changes, Sub-Agent Number changes, import preview/confirm/cancel/failure, report previews and report exports. Import audit metadata includes safe filename, file hash, agency, date and counts only; it does not include workbook row contents, cookies, tokens or credentials.

## Deployment And Migration Notes

Phase 4 adds migration `0005_phase4_tpm_uniqueness_omission_active.py` for active omission history and case-insensitive TPM-code uniqueness. The migration is additive except replacing the old omission uniqueness constraint with an active-only uniqueness constraint. No live Render database operations are required during local development.

## Known Limitations

PDF export, emailed reports, scheduled reports, destructive cleanup and automatic tax deduction remain out of scope. Excel import supports the confirmed five-sheet daily-sales workbook only; unrelated workbook formats are rejected. Deployment still uses Render for Django/PostgreSQL and Vercel for Next.js.

## Terminal register and historical identity

The compatibility model `TPMCode` means Sub-Agent Number. `TerminalNumber` stores a distinct textual identifier with protected links to that Sub-Agent Number, person and agency; owner and agency must agree with the database Sub-Agent relationship. Terminal identifiers are globally case-insensitive unique, including inactive records. Each Sub-Agent Number has at most one active terminal. Inactive records and immutable audit old/new values retain assignment history. Person and Sub-Agent owner changes cannot bypass linked terminal reassignment.

`TerminalImportBatch` stores uploader, agency, sanitized filename, SHA-256 hash, preview status/summary, normalized rows, warnings/errors, one-hour expiry, confirmation time and result counts. Preview creates batch metadata only. There is no permanent raw workbook storage. Import audit contains metadata/counts rather than row contents. Uploader ownership and current role are checked at every endpoint.

All terminal mutations/import/history are Super Admin-only; Accountants have agency-scoped read access. Reassignment is a dedicated atomic, row-locked action with verified target IDs, reason and confirmation. Cross-agency changes are permitted only to Super Admin and displayed explicitly. Occupied targets require separate, explicit deactivation before replacement. Bulk import never performs reassignment implicitly.

New daily transactions store `terminal_number_snapshot`; `tpm_code_snapshot` remains the Sub-Agent snapshot compatibility field. Historical blanks stay blank. Reports use snapshots, split detail rows when recorded terminal identity differs, and preserve existing financial calculations and person totals. Existing five-sheet workbooks remain accepted through a visible legacy fallback where unambiguous; system-register conflicts are blocking, never silently resolved. No mappings are inferred by migrations.

See the backend README?s Terminal Number register section for the exact API contract, conflict classifications, safety limits, locking and rollout procedure. Migrations 0011/0012 are additive/schema-display changes; `terminal_readiness` is read-only.

Formal SRS remains unchanged. Later amendments are needed in: terminology/glossary, entity relationships and constraints, terminal lifecycle and role matrix, workbook field mapping/preview workflow, historical identity/report output, audit/data retention, API/proxy security, migration/transition requirements, and acceptance tests. Teller/Cashier is outside this change.

## Standalone Payment System

Payments are a separate domain from Daily Sheets. Payers belong to agencies and link existing same-agency Sub-Agent Numbers. Each payer can own multiple obligations. Obligations require a description, date and positive expected total; partial payments are supported and status is derived as Open, Partially Paid, Paid or Cancelled. A cancelled obligation cannot receive a payment. Posted payments are immutable; correction is a Super Admin reversal followed by a new payment.

The payment API exposes payer, obligation, payment and analytics resources. Accountants receive only assigned active-agency records and must have the relevant create/edit/delete assignment flag for mutations. Super Admin has cross-agency access, reversal authority, recorder filtering and agency breakdown analytics. Queryset scoping and mutation checks both enforce this contract, including direct object IDs and agency query parameters. No Teller/Cashier role exists.

Posting locks the obligation before checking the outstanding balance. Idempotency keys are required and identical retries return the original record. Obligation and receipt numbers are allocated with a database-backed yearly sequence, not `MAX()+1` or row counts. Payment and reversal changes are atomic. Payment snapshots preserve agency, payer, obligation and linked Sub-Agent identity for receipts. Reversed records remain visible but are excluded from current posted and active collection totals.

Analytics define obligation dates as portfolio filters and stored payment dates as collection filters; both ranges are inclusive. Portfolio totals include expected, current posted, outstanding, collection rate and status counts. Collections report gross postings, reversed amounts separately, net collected, receipt counts and payment-method totals. Trends are daily for short ranges and monthly for long ranges with zero-filled requested periods. Division by zero returns zero. Financial totals remain backend Decimal calculations.

The frontend uses `/dashboard/payments`, `/dashboard/payments/payers`, `/dashboard/payments/obligations`, `/dashboard/payments/receipts/{id}` and `/dashboard/payments/analytics`. Its controlled proxy allowlist permits only the required payment methods and exact receipt GET route. CSRF protects mutations, JWTs remain HTTP-only, PDF receipts remain binary and browser storage is not used for tokens, payment data or idempotency keys.

Payment audit entries are immutable and metadata-only for payer lifecycle, Sub-Agent assignment, obligations, posting and reversal. Names, notes, free-text reasons, tokens, credentials and complete request bodies are not logged. Receipt-view audit is not enabled because it is not part of the established audit policy.

Migrations `0014`–`0018` are additive and ordered after `0013`: payment domain tables and assignment constraints, snapshot/default refinements, recorded-user display snapshot, yearly number sequence and named financial/reversal constraints. `makemigrations --check` passes for SQLite and PostgreSQL settings. Local PostgreSQL concurrency tests are required because SQLite does not prove row-lock behavior.

Acceptance/UAT scenarios include agency-isolated payer search, same-agency Sub-Agent linking and confirmed reassignment, obligation creation and cancellation rules, partial payment posting, duplicate retry, overpayment rejection, receipt download, Super Admin-only reversal, reversed receipt visibility, analytics date boundaries and zero rate, Accountant direct-ID isolation, audit metadata safety, and responsive payment tables. Formal SRS source files were not present in the repository; this section is the Markdown amendment text for the eventual SRS update.
