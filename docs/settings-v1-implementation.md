# Settings Version 1

The desktop sidebar used a viewport-height flex container without a bounded,
scrollable navigation child. As the menu grew, its minimum content height exceeded
the available height. The mobile drawer also lacked an internal scroll region.
Navigation now uses `min-height: 0`, remaining flex space and vertical overflow.
Branding and Logout remain outside that region. The desktop sidebar remains sticky;
the mobile/tablet drawer uses a native modal dialog for focus containment and Escape,
locks background scrolling and restores focus to the menu trigger. Active-item
styling and the existing logo are preserved.

## Settings and access

`GET /api/organisation-settings/` and `PATCH /api/organisation-settings/` require
an authenticated Super Admin in Django. Accountants receive 403 and the dashboard
settings route displays AccessDenied. My Profile remains available to all
authenticated users. The controlled frontend proxy allows only GET and PATCH on
this exact settings path; it exposes no detail, history or arbitrary configuration
routes.

Editable fields: display name (160), address (500), telephone (40), contact email
(254), receipt heading (120), receipt footer (500), IANA timezone (64), and one of
`YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`. Email, telephone, timezone, required names,
lengths and control characters are validated. Unknown and financial fields are
rejected, including mixed valid/invalid requests. Fields are explicit database
columns, not a generic configuration store.

Read-only cards expose Nigerian Naira (NGN), ₦, the current 2% Daily Sheet policy,
historical snapshot guidance, application name, Settings Version 1 and access role.
The form has Edit, Save and Cancel, field errors, a synchronous duplicate-submit
guard, saving state, success feedback, load retry and preserved edits after failures.
The configured display name appears in the Settings dashboard heading. Existing
Treasureland branding and its logo are unchanged.

## Receipts and financial history

PDF downloads use the current organisation name, address, telephone/email, receipt
heading and footer. These strings are escaped before ReportLab renders them.
Timezone/date format apply to the **generation timestamp in the header**.
The original payment timestamp in the transaction table remains unchanged.

Only header/footer presentation can reflect current settings when an existing
receipt is downloaded again. Previously downloaded files are unaffected. Payment,
obligation, game, payer, Sub-Agent and Terminal identity/financial snapshots remain
stored and unchanged. Receipt identifiers, amounts, historical commission rates,
schedules and Daily Sheet snapshots cannot be changed through Settings.

## Storage and audit

Migration `0026_alter_auditlog_action_organisationsettings` adds the singleton model
and the organisation-settings audit action choice. Its fixed primary key and
database check constraint permit only record 1. No existing financial records are
backfilled or changed. Reads return safe defaults without writing; the first valid
PATCH creates the record. Concurrent edits use a transaction and row lock.
Defaults: Treasureland Investment Limited, Africa/Lagos, YYYY-MM-DD, Payment Receipt,
and Thank you for your payment; contact details default to empty.

Changes and their audit event commit atomically. Audit metadata contains only sorted
changed field names and actor ID. The normal AuditLog columns carry the actor,
timestamp and safe record identifier. No old/new contact values, bodies, tokens or
secrets are logged. No-op saves add no audit event. Existing audit immutability and
read-only history endpoints remain in force.

## Changed files

- Backend: `core/models.py`, `core/organisation_settings.py`, `core/urls.py`,
  `core/views.py`, `core/audit_profile.py`,
  `core/migrations/0026_alter_auditlog_action_organisationsettings.py`,
  `core/tests/test_organisation_settings.py`.
- Frontend: `app/dashboard/settings/page.js`, `components/SettingsClient.js`,
  `components/DashboardShell.js`, `app/globals.css`, `lib/controlled-proxy-path.js`,
  `tests/organisation-settings.test.mjs`, `tests/settings-sidebar-layout.mjs`,
  `tests/chromium-viewport.mjs` (honors requested height as well as width).
- Documentation: this file.

## Verification

All Django commands use `--settings=config.test_settings`, an isolated in-memory
SQLite database. No production data or application database is accessed or migrated.

- Focused settings tests: 5 passed.
- Django system check: no issues; migration drift check: no changes detected.
- Complete Django suite: 296 tests, 10 skipped for PostgreSQL/row-lock capabilities.
- Complete frontend suite: 183 passed.
- Frontend lint and production build passed.
- Chromium regression checks: 1366×600, 1280×720, 1024×600, 768×600, 390×640,
  320×568. Checks use actual compiled components and production CSS, assert bounded
  page width, independent menu scrolling, every link's focus reachability, Settings,
  My Profile, Logout, active indication, modal behavior and sticky position.
- React interaction tests additionally cover mobile open/close/Escape/focus restore
  and accountant navigation, plus settings validation/network errors and save states.
- `git diff --check` passed. Work remains uncommitted; no push or deployment performed.

Run layout checks after building with `CHROME_HEADLESS_PATH` set to local Chromium:
`node tests/settings-sidebar-layout.mjs` from `frontend`.
