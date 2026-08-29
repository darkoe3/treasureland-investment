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
Commission Minus Tax = Commission - Tax
Variance = Incoming Funds - Total To Pay
Premier Office Payment = Incoming Funds - Commission Minus Tax
```

`variance_status` is `BALANCED`, `SHORTFALL` or `EXCESS`.

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
- `GET /api/audit-logs/`
- `GET /api/audit-logs/{id}/`
- `GET|POST /api/accountants/`
- `GET|PATCH /api/accountants/{id}/`
- `POST /api/accountants/{id}/set-agencies/`
- `POST /api/accountants/{id}/reset-password/`
- `POST /api/accountants/{id}/activate/`
- `POST /api/accountants/{id}/deactivate/`

Accountant management action URLs are hyphenated DRF action paths. Use `set-agencies` and `reset-password`, not the Python method names `set_agencies` or `reset_password`, and keep Django's trailing slash.

Daily sheets support `agency`, `date`, `date_from`, `date_to`, `status` and `created_by` query filters.

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
- Confirm accountant management audit logs do not expose password values.
