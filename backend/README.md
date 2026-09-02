# Treasureland Backend

## Phase 2 Relationships

- `DailySheet` belongs to one active `Agency` and one `transaction_date`.
- `DailySheetGame` snapshots the active `WeeklyGameSchedule` rows for the sheet weekday.
- `TPMDailyTransaction` records one active `TPMCode` on a `DailySheet`.
- `TransactionGameSale` stores one monetary amount per transaction and sheet game.
- `OmittedTerminal` explains active TPM codes not entered on a sheet.
- `AuditLog` records immutable sheet, transaction, omission and workflow changes.

## Calculation Formulas

All monetary values use `Decimal`, two decimal places and `ROUND_HALF_UP`.

```text
NET Sales = sum of game sales for a TPM code
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
- `REGISTER SUB-AGENT`: maps `SUB AGT NOS` to `TERMINAL NOS`; `TERMINAL NOS` is the system `TPMCode.code`.
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

Phase 4 completes daily operations using the existing core models. Accountants can manage people, TPM codes, sheets, transaction rows and omissions only for assigned agencies where the relevant permission flag allows it. The backend enforces object-level agency checks.

TPM code uniqueness is enforced case-insensitively. People and TPM codes are safely deactivated so transaction history remains intact. Omitted-terminal removals mark records inactive to preserve history.

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
