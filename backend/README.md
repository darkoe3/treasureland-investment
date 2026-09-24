# Treasureland Backend

## Phase 2 Relationships

- `DailySheet` belongs to one active `Agency` and one `transaction_date`.
- `DailySheetGame` snapshots the active `WeeklyGameSchedule` rows for the sheet weekday.
- `TPMDailyTransaction` records one active `TPMCode` on a `DailySheet`.
- `TransactionGameSale` stores one monetary amount per transaction and sheet game.
- `OmittedTerminal` explains active Sub-Agent Numbers not entered on a sheet.
- `AuditLog` records immutable sheet, transaction, omission and workflow changes.

## Calculation Formulas

All monetary values use `Decimal`, two decimal places and `ROUND_HALF_UP`.

```text
NET Sales = sum of game sales for a Sub-Agent Number
Commission = NET Sales x 5%
To Pay = NET Sales x 95%

Subagent Share = Subagent NET Sales x 2%
Organisation Share = Subagent NET Sales x 3%

Gross Sales = sum of NET Sales
Total To Pay = sum of To Pay
Variance = Incoming Funds - Total To Pay
```

`variance_status` is `BALANCED`, `SHORTFALL` or `EXCESS`.

Manual tax is recorded for reporting and reconciliation only. It does not reduce To Pay.

## Status Workflow

- `DRAFT`: accountant may edit assigned agencies when permission flags allow it.
- `SUBMITTED`: locked against accountant editing; Super Admin may approve or return.
- `APPROVED`: locked against accountant editing; Super Admin may reopen.
- `RETURNED`: accountant may correct and resubmit; return comment is visible.
- `REOPENED`: accountant may correct and resubmit; reopen reason is required.

## API Endpoints

- `GET|POST /api/daily-sheets/`
- `GET|PATCH|PUT|DELETE /api/daily-sheets/{id}/`
- `POST /api/daily-sheets/{id}/submit/`
- `POST /api/daily-sheets/{id}/approve/`
- `POST /api/daily-sheets/{id}/return/`
- `POST /api/daily-sheets/{id}/reopen/`
- `GET /api/daily-sheets/{id}/summary/`
- `GET|POST /api/tpm-daily-transactions/`
- `GET|PATCH|PUT|DELETE /api/tpm-daily-transactions/{id}/`
- `GET|POST /api/omitted-terminals/`
- `GET|PATCH|PUT|DELETE /api/omitted-terminals/{id}/`
- `GET /api/games/for-date/?date=YYYY-MM-DD`
- `POST /api/daily-sheet-imports/preview/`
- `GET /api/daily-sheet-imports/{id}/`
- `POST /api/daily-sheet-imports/{id}/confirm/`
- `POST /api/daily-sheet-imports/{id}/cancel/`
- `GET /api/audit-logs/`
- `GET /api/audit-logs/{id}/`
- `GET|POST /api/accountants/`
- `GET|PATCH /api/accountants/{id}/`
- `POST /api/accountants/{id}/set-agencies/`
- `POST /api/accountants/{id}/reset-password/`
- `POST /api/accountants/{id}/activate/`
- `POST /api/accountants/{id}/deactivate/`
- `GET /api/reports/agency-summary/?agency={id}&period=daily&date=YYYY-MM-DD`
- `GET /api/reports/agency-summary/?agency={id}&period=weekly&date=YYYY-MM-DD`
- `GET /api/reports/agency-summary/?agency={id}&period=monthly&month=1-12&year=YYYY`
- `GET /api/reports/agency-summary/?agency={id}&period=custom&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `GET /api/reports/agency-summary/export/` with the same query parameters

Accountant management action URLs are hyphenated DRF action paths. Use `set-agencies` and `reset-password`, not the Python method names `set_agencies` or `reset_password`, and keep Django's trailing slash.

Daily sheets support `agency`, `date`, `date_from`, `date_to`, `status` and `created_by` query filters.

Reports are Super Admin-only and default to `status=APPROVED`. Repeated `status` query parameters are allowed for operational/non-final reports. Accountants receive `403`, even when `can_export=True`.

Report game columns are the union of included `DailySheetGame` snapshots. Stable game IDs are preferred; normalized snapshot names are the fallback for legacy records. Ordering is display order, normalized name and stable key.

Excel exports are generated with `openpyxl`, use numeric monetary cells, sanitize filenames and worksheet names, and prefix user-controlled text that begins with `=`, `+`, `-` or `@` to prevent formula injection.

## Daily Sheet Excel Import

Accountants with `can_create` for an assigned agency and Super Admin users can preview one `.xlsx` workbook under `POST /api/daily-sheet-imports/preview/`. The parser supports the shared five-sheet agency workbook structure:

- `ENTER GAME DATA HERE`: selected raw-sales source. `B2` is advisory workbook date, `B5:B224` is `SUB AGT NOS`, `C:I` are raw game sales, and row 3 supplies game headers.
- `REGISTER SUB-AGENT`: comparison data for the system register. `SUB AGT NOS` is the existing `TPMCode.code`; `TERMINAL NOS` is a separate registered terminal.
- `MUSA RESULTS`, `Premier Games` and `Sheet2`: recognized but not imported as authoritative transaction data.

The import reads only raw game-sales amounts. Django recalculates NET Sales, 5% commission, 95% To Pay, sub-agent share, organisation share, tax and difference using the existing model properties. Workbook formulas and cached legacy totals are advisory only.

Preview creates a server-side `DailySheetImportBatch` containing safe metadata, normalized rows, warnings and blocking errors. The raw workbook is not stored. Confirmation uses the stored batch, not browser-submitted transaction rows, and writes atomically. If no sheet exists, confirmation creates a Draft sheet and snapshots the current active games for that date, including Whole Day games. If an editable Draft already has transactions, confirmation requires `replace_existing=true` and replaces all rows instead of merging. Submitted and Approved sheets are protected, and any changed target sheet or changed row count after preview requires a fresh preview.

Security limits include `.xlsx` signature checks, 5 MB upload size, bounded sheet/row/column inspection, ZIP decompression limits, macro/external-link/embedded-content rejection, formula rejection in transactional sales cells, sanitized filenames, metadata-only audit records and no logging of workbook contents, cookies, JWTs or credentials.

## Example Transaction Request

```json
{
  "daily_sheet": 1,
  "tpm_code": 12,
  "sales": [
    {"daily_sheet_game": 1, "amount": "23270.00"},
    {"daily_sheet_game": 2, "amount": "13805.00"}
  ]
}
```

## Example Submission Request

```http
POST /api/daily-sheets/1/submit/
Authorization: Bearer <token>
```

When variance is not zero, set `reconciliation_note` on the sheet before submission.

## Local Commands

```text
.\.venv\Scripts\python.exe manage.py makemigrations --check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test
```

Frontend:

```text
npm run lint
npm run build
```

## First Staging Deployment

Render hosts the Django service and PostgreSQL database. Use the backend directory as the service root.

Render build command:

```text
bash render-build.sh
```

Render start command:

```text
gunicorn config.wsgi:application
```

Required Render environment variables:

- `SECRET_KEY`: generated secret value.
- `DEBUG`: `False`.
- `DATABASE_URL`: Render PostgreSQL internal connection string.
- `ALLOWED_HOSTS`: comma-separated Render hostnames, for example the Render service host.
- `CORS_ALLOWED_ORIGINS`: comma-separated Vercel frontend origins with `https://`.
- `CSRF_TRUSTED_ORIGINS`: comma-separated Vercel frontend origins with `https://`.
- `JWT_ACCESS_MINUTES`: usually `10`.
- `JWT_REFRESH_DAYS`: usually `7`.
- `TIME_ZONE`: `Africa/Accra`.

Optional hardening variables after the HTTPS custom domain is verified:

- `SECURE_SSL_REDIRECT=True`
- `SECURE_HSTS_SECONDS=31536000`
- `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`
- `SECURE_HSTS_PRELOAD=True`

Do not store database credentials, domains or secrets in source control. Keep the public health check minimal at `GET /api/health/`; it returns only `{"status":"ok"}`.

## Known Assumptions

- Draft sheets may leave `incoming_funds` and `tax` blank until submission.
- Accountants submit sheets through their assigned agency edit permission.
- Reopen reason is stored in `reopen_reason` and audit history.
- All five agencies share the same active weekly game schedule for a weekday.

## Phase 3 Authentication And Accountants

The Next.js frontend acts as a Backend-for-Frontend. It sends credentials to Django, stores JWTs only in HTTP-only cookies, and calls protected Django endpoints from server-side route handlers. Django remains the source of truth for authentication and authorization.

`GET /api/auth/me/` returns safe profile data:

- Super Admin: role, profile and all active agencies.
- Accountant: role, profile and assigned agencies with permission flags.

Super Admin accountant management uses `/api/accountants/`. Passwords are validated with Django password validators and saved with `set_password()`. Accountant deactivation keeps historical daily sheets, transactions and audit records intact.

For Render/Vercel deployment, configure:

- Backend: `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` with the Vercel origin.
- Frontend: server-only `API_BASE_URL` pointing to the Render `/api` base URL.

Manual checks for the training manual:

- Confirm inactive accountants cannot log in.
- Confirm accountants see only assigned agencies.
- Confirm Super Admin can assign separate permission flags per agency.

## Phase 4 And 5 Notes

Phase 4 completes daily operations using the existing core models. Accountants can manage people, Sub-Agent Numbers, sheets, transaction rows and omissions only for assigned agencies where the relevant permission flag allows it. The backend enforces object-level agency checks.

Sub-Agent Number uniqueness is enforced case-insensitively. People and Sub-Agent Numbers are safely deactivated so transaction history remains intact. Omitted-terminal removals mark records inactive to preserve history.

Manual tax is stored on `DailySheet` but does not reduce calculated To Pay. Difference remains `incoming_funds - total_to_pay`.

Run local verification without connecting to staging:

```bash
python manage.py makemigrations --check
python manage.py check
python manage.py test
```
- Confirm accountant management audit logs do not expose password values.
- Confirm report audit logs include metadata only, not full report contents.
- Phase 5 adds migration `0006_alter_auditlog_action.py` for report preview/export audit action choices. No destructive schema or data migration is required.

## Terminal Number register

`TPMCode` is the compatibility backend/table name for **Sub-Agent Number**. Its IDs, values, relationships and historical snapshots are retained. `TerminalNumber` is separate: one globally case-insensitive terminal identifier (text, trimmed, leading zeroes retained), linked by protected foreign keys to a Sub-Agent Number, its current person and agency. A conditional database constraint permits at most one active terminal per Sub-Agent Number. Inactive identifiers remain reserved; reuse requires the dedicated Reassign action. Terminal edits are audited and do not rewrite transaction snapshots.

All terminal mutations, template download, import and assignment history are Super Admin-only. Accountants can list/retrieve terminals only in assigned agencies. The existing People/Sub-Agent permission flags remain unchanged; changing a person?s agency or a Sub-Agent Number?s owner is blocked while terminal records refer to that relationship. Reassign the terminal records first. Terminal audit events are excluded from Accountant access through the generic audit endpoint to avoid revealing cross-agency history.

Endpoints (Django trailing slash):

- `GET|POST /api/terminal-numbers/`
- `GET|PATCH /api/terminal-numbers/{id}/` (PATCH accepts only `terminal_number`)
- `POST /api/terminal-numbers/{id}/deactivate/`
- `POST /api/terminal-numbers/{id}/reactivate/`
- `POST /api/terminal-numbers/{id}/reassign/`
- `GET /api/terminal-numbers/{id}/history/`
- `GET /api/terminal-number-imports/template/?agency={id}`
- `POST /api/terminal-number-imports/preview/` (multipart `agency`, `file`)
- `GET /api/terminal-number-imports/{id}/`
- `POST /api/terminal-number-imports/{id}/confirm/` (`confirmed: true`)
- `POST /api/terminal-number-imports/{id}/cancel/`

List filters: `search`, `agency`, `active=true|false`. Create accepts `agency`, `person`, `sub_agent_number` (existing TPMCode ID), `terminal_number` (string), and `is_active` (boolean). The backend resolves and verifies the owner/agency, never trusting independent client relationships. Reassign requires all three target IDs, nonblank `reason` (maximum 2,000 characters), and `confirmed: true`. Cross-agency reassignment is allowed only for Super Admin. An occupied active target must be explicitly deactivated first. Reassignment preserves the terminal?s active status; reactivation is separate.

Mutations and batch confirmation use `transaction.atomic()` with deterministic agency and row locks. Parent agency locks serialize empty assignment slots as well as existing records; database uniqueness is the final race safeguard. PostgreSQL supplies row locks; SQLite tests verify constraints/rollback but cannot prove PostgreSQL concurrency behavior. There is no terminal DELETE endpoint. Existing audit immutability protections also reject upsert-style bulk mutation.

The template is a blank first worksheet with `S/NOS | SUB AGT NOS | TERMINAL NOS | NAME`; data starts at row 2. B/C are preformatted as text for 500 rows, and instructions are separate. Import supports up to 5,000 rows, 20 columns and 10 sheets with existing 5 MB compressed / 30 MB expanded package limits. It rejects formulas in B?D, macros/external links, missing or mismatched names, partial rows and case-insensitive workbook duplicates. S/NOS is ignored. Numeric identifiers warn about potential leading-zero loss; text cells do not. It creates neither People nor Sub-Agent Numbers.

Preview saves only a dedicated batch, safe normalized rows, validation messages and metadata; no terminal assignments or raw workbook files. Batches expire after one hour and are private to their uploader, including between Super Admins. Confirmation revalidates identities and mappings under locks and rolls back all rows on failure. Only `New` and `Unchanged` rows can confirm. `Update required` (inactive same mapping), `Reassignment required` (terminal belongs elsewhere), and `Conflict` (target occupied or invalid row) block confirmation: use Reactivate/Reassign/Deactivate manually, then upload a fresh preview. Whitespace/case variants of an existing terminal are Unchanged and preserve its spelling.

Daily five-sheet imports match SUB AGT NOS to the existing model and compare workbook registration with the system terminal. Missing workbook registration can resolve from the system. Conflicts block import. Legacy column-C matching remains only when neither a known contradictory Sub-Agent Number nor terminal history exists; it emits a warning and does not infer a terminal. Confirmation rejects changed identities/terminal assignments after preview. The parser materializes bounded worksheet regions once to avoid repeatedly reparsing streaming XML.

New daily transactions snapshot terminal text alongside existing person/Sub-Agent snapshots. Reports group detail by stored identity including terminal snapshot; old blanks display `Not recorded`. No commission, To Pay, tax or reconciliation formula changes.

Additive migrations: `0011_terminal_number_register` adds the two models, indexes/constraints, terminal snapshot (blank default), and audit choices; `0012_sub_agent_display_name` changes display metadata only. Neither migration creates mappings, renames tables, deletes identities nor updates existing snapshot values. Review/apply migrations to the intended database as part of your normal release procedure; implementation testing uses an isolated database.

Read-only readiness: `python manage.py terminal_readiness` reports active Sub-Agent Numbers without terminals, inactive Sub-Agent Numbers, duplicate terminal/active mappings, relationship conflicts and historical blank snapshots. There is no write mode.

For isolated tests: `python manage.py test --settings=config.test_settings`. This forces an in-memory SQLite database and a fast test-only password hasher; never use that settings module for serving the application.

## Standalone payments

Payments are an independent ledger; they do not read from or write to `DailySheet`, `TPMDailyTransaction` or daily-sheet reports. A `PaymentPayer` belongs to one agency and may link active existing Sub-Agent Numbers from that agency. A payer can have multiple `PaymentObligation` records. Obligations move from `OPEN` to `PARTIALLY_PAID` to `PAID`, or to `CANCELLED` before posted payments. Partial payments are allowed.

Payment endpoints include `payment-payers`, `payment-obligations`, `payer-payments` and `payments/analytics`. Lists are agency-scoped for Accountants and paginated. Supported filters include agency, payer, active/status, payer-name or description search, obligation number/date range, outstanding-only, receipt, payment method/date range and Super Admin-only recorder filters. Direct object IDs are scoped by the same queryset rules.

Super Admin has access to all agencies, can manage payers and obligations, record payments, reverse posted payments and view all analytics. Accountants can act only in assigned active agencies and only with the relevant `can_create`, `can_edit` or `can_delete` flag. Accountants cannot reverse payments or inspect another agency by changing a query parameter or guessing an ID. There is no Teller/Cashier role.

Payment posting requires a positive amount, an idempotency key and a non-cash reference when applicable. The obligation row is locked before the balance check; yearly obligation and receipt numbers use the locked `PaymentNumberSequence` row. A retry with identical payment data returns the original payment. Posted payments cannot be edited or deleted. Corrections use Super Admin reversal with confirmation and a required reason; the original receipt and snapshots remain visible.

Analytics use Decimal-backed aggregates. The obligation portfolio reports expected, current posted, outstanding, collection rate and status counts. Collections report gross postings, reversals separately and net collected as gross minus reversals; active posted totals exclude reversed records. Payment dates filter collections and obligation dates filter the portfolio, both inclusively. Trends are daily for short ranges and monthly for longer ranges, with zero-filled periods where a range is supplied. Zero expected amounts produce a zero rate.

Payment audit entries cover payer, Sub-Agent assignment, obligation, posting and reversal actions. Metadata contains IDs, state and safe financial identifiers only; payer names, notes, free-text reasons, credentials, tokens and complete request bodies are excluded. Receipt PDFs use stored payment snapshots. Migrations `0014` through `0018` add the payment tables, snapshots, yearly sequence and named positive/reversal constraints without destructive data operations.

Local verification uses the isolated settings modules:

```text
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --settings=config.test_settings
python manage.py test --settings=config.test_settings
python manage.py test core.tests.test_payment_management core.tests.test_payment_gate1b core.tests.test_payment_postgresql --settings=config.postgres_test_settings
```

The PostgreSQL payment settings require loopback host access and let libpq read credentials outside the repository from the local `pgpass.conf`. PostgreSQL concurrency coverage verifies locked balances, idempotency, reversals and yearly numbering. Known limitations are that receipt-view audit events are not enabled by the established audit policy, and local SQLite cannot prove PostgreSQL locking behavior; the isolated PostgreSQL suite must be run for that assurance.
