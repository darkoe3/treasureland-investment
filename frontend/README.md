# Treasureland Frontend

## Local Startup

```text
npm install
npm run dev
```

Run the Django backend separately, usually at `http://127.0.0.1:8000/api`.

Create `frontend/.env.local`:

```text
API_BASE_URL=http://127.0.0.1:8000/api
```

`API_BASE_URL` is server-only. Do not expose backend secrets or JWTs through `NEXT_PUBLIC_*`.

## Vercel Staging Configuration

Set this environment variable in Vercel:

```text
API_BASE_URL=https://your-render-service.onrender.com/api
```

Do not set `NEXT_PUBLIC_API_BASE_URL`. Browser code must keep calling same-origin Next.js route handlers under `/api/auth/*` and `/api/backend/*`; those handlers forward to Django from the server side.

Production deployments must use HTTPS. The JWT cookies are HTTP-only, use `sameSite: "lax"`, and use `secure: true` when `NODE_ENV=production`, which is the Vercel production build/runtime default.

## Authentication Architecture

The browser calls Next.js Route Handlers under `/api/auth/*`. Those handlers call the Django REST API, then store JWT access and refresh tokens in HTTP-only cookies:

- `tl_access`: short-lived access token
- `tl_refresh`: longer-lived refresh token
- `tl_csrf`: readable CSRF token used only to protect state-changing cookie-authenticated requests

JWTs are never stored in `localStorage` or `sessionStorage` and are never returned to client components.

Cookie settings:

- `httpOnly: true` for JWT cookies
- `secure: true` in production
- `sameSite: "lax"`
- `path: "/"`

## CSRF Protection

Client mutations first request `/api/auth/csrf`, then send the returned token in the `x-csrf-token` header. Login, logout, refresh and the controlled backend proxy reject missing or mismatched CSRF tokens.

## Route Protection

Next.js 16 uses `proxy.js` for request interception. The proxy protects `/dashboard/:path*`, validates the access token against Django, attempts one refresh with the refresh token when needed, and writes refreshed cookies onto the browser response.

Every protected dashboard page also verifies the current user server-side. Backend authorization remains the final authority.

## Accountant Management

Super Admin users can open:

- `/dashboard/accountants`
- `/dashboard/accountants/new`
- `/dashboard/accountants/[id]`

The screens call Super Admin-only Django endpoints through the controlled Next.js backend proxy. Agency permission flags are configured independently per agency.

## Phase 5 Reports

`/dashboard/reports` is a Super Admin-only reporting screen. Accountants receive an access-denied page and the Reports navigation item is not shown to them, even when an agency assignment has `can_export`.

The page supports daily, weekly, monthly and custom inclusive date ranges. Weekly display resolves Monday through Sunday; monthly display resolves the calendar month, including leap years. Statuses default to Approved only. Including Draft, Submitted, Returned or Reopened shows an operational/non-final warning.

Preview requests use `GET /api/backend/reports/agency-summary/`. Excel downloads use `GET /api/backend/reports/agency-summary/export/` and are forwarded through the same-origin BFF as binary `.xlsx` responses. The BFF allowlist permits only those exact report paths and GET methods, preserves backend status codes, preserves `Content-Type` and safe `Content-Disposition`, and does not expose JWTs to browser JavaScript.

Report data is kept in React state only. It is not written to `localStorage` or `sessionStorage`.

## Phase 4 Screens

- `/dashboard/people`: search, filter, create and edit people; add and safely deactivate TPM codes.
- `/dashboard/daily-sheets`: list, filter and create daily sheets.
- `/dashboard/daily-sheets/[id]`: enter transactions, record omissions, update manual tax and actual received, review totals and run workflow actions.
- `/dashboard/daily-sheets/import`: upload an approved `.xlsx` daily-sheet workbook, preview validation results and confirm import into Draft sheets.

All browser requests use `/api/backend/...`; the controlled proxy allowlist permits only exact operational and report paths and methods.

## Daily Sheet Excel Import

The Daily Sheets page includes `Upload Excel`. The import screen asks for agency, transaction date and one `.xlsx` file up to 5 MB. Accountants see only agencies where they have `can_create`; Super Admin users can select any active agency.

Preview uploads multipart form data through the controlled backend proxy to `POST /api/daily-sheet-imports/preview/`. The browser displays agency/date, safe filename, valid rows, ignored blank/zero rows, canonical game mappings, per-row game amounts, NET Sales, To Pay, warnings, blocking errors and existing Draft replacement status. Confirmation remains disabled while blocking errors exist. Existing Draft replacements require an explicit checkbox, and workbook date mismatches require explicit acknowledgement.

Confirmation calls `POST /api/daily-sheet-imports/{id}/confirm/` with acknowledgement flags only; normalized rows stay server-side in the import batch. A successful import redirects to the normal daily-sheet detail page for review, where manual entry and the existing submit/return/reopen/approve workflow continue unchanged. The preview can be cancelled with `POST /api/daily-sheet-imports/{id}/cancel/`.

The proxy allowlist permits only the exact import endpoints and methods. Multipart bodies are forwarded as `FormData` without forcing JSON content type, CSRF is still required for mutations, one-refresh retry preserves the file and form fields, and JWTs remain HTTP-only cookies.

Run local verification:

```bash
npm run test:auth
npm run lint
npm run build
```

## Troubleshooting

- Expired session: sign in again if refresh has expired or was blacklisted.
- CORS: add the Vercel frontend origin to backend `CORS_ALLOWED_ORIGINS`.
- Django CSRF trusted origins: add the same frontend origin to `CSRF_TRUSTED_ORIGINS`.
- Production cookies: HTTPS is required because JWT cookies use `secure: true`.
- Django trailing slashes: frontend backend requests are normalized to Django router paths such as `/api/accountants/` before query strings.
- Accountant assignment saves: the form must call the controlled proxy with `/api/backend/accountants/{id}/set-agencies/`; the proxy then forwards `POST /api/accountants/{id}/set-agencies/` to Django. A slash mismatch can show up as a 308 redirect followed by a 404.
- Controlled proxy path rejection: the Next.js 16 catch-all route awaits `context.params` and normalizes the mounted `/api/backend` prefix out of `params.path` before comparing against the allowlist. Set `TL_PROXY_DEBUG=1` temporarily to log method, catch-all segments, normalized path and final backend URL; request bodies, cookies and tokens are not logged.
- Partial accountant saves: if profile fields save but agency permissions fail, the form reports a partial save and keeps the selected agency permissions on screen for retry.
- Upstream errors: expected JSON validation errors are shown; unexpected HTML/debug responses are replaced with a generic message.
- Excel download errors: report export errors preserve the backend status and JSON message; successful downloads preserve the workbook content type and filename.
- Excel import errors: confirm the file is `.xlsx`, under 5 MB, has the five required worksheets, uses `SUB AGT NOS` from `ENTER GAME DATA HERE`, maps those values to `TERMINAL NOS` in `REGISTER SUB-AGENT`, and uses row-3 game headers that match the selected date's daily-sheet game snapshots.
- Empty agency permissions: the accountant form accepts both plain API arrays and paginated `{results: [...]}` responses. Missing `is_active` is treated as active; explicit `is_active: false` is hidden.
- Failed agency loading: edit forms keep profile saving available but do not replace agency assignments until the agency list loads successfully.

## Manual Verification Checklist

- Login succeeds with a valid staff account and returns no token values to browser JavaScript.
- Invalid login shows a validation message and sets no auth cookies.
- `/dashboard` redirects unauthenticated users to `/login?next=/dashboard`.
- Super Admin can list, create, edit, deactivate, activate and reset passwords for accountants.
- Accountants see only assigned-agency navigation and receive access denied on accountant-management routes.
- Accountants receive access denied on Reports and 403 from direct report API/export attempts.
- Super Admin can generate Approved official reports and labelled operational/non-final reports with other statuses.
- Wide report tables scroll internally without widening the dashboard shell.
- Logout clears auth cookies and returns to `/login`.
