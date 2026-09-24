# Agency Management implementation report

Implemented on 2026-09-23. Existing uncommitted documentation edits and untracked files were preserved. No commit, push, deployment, production-data access, SRS edit, or Teller/Cashier implementation was performed.

## Previous limitation and implementation

Both agency navigation destinations displayed placeholders. The existing agency API provided generic CRUD without dedicated lifecycle confirmations, case-insensitive uniqueness, summary/impact information, or agency audit events. Some dependent writes and historical report queries did not handle inactive agencies consistently.

The existing API now powers responsive agency cards, search and status filters, details, field-level validation, success/error/loading states, and native modal confirmation dialogs. The accountant Assigned Agencies destination reuses the same screen with read-only controls and backend-scoped results. Counts include inactive records; impact counts separately identify active dependents and editable sheets.

Edits update the original agency ID. Relationships, import records, daily sheets, transaction identity snapshots, reports, and prior audit records remain intact. Agency deletion is unavailable through the API or Django admin. Django admin agency records are read-only so lifecycle changes use the audited workflow.

## Endpoints

All paths below are under `/api/` in Django. The existing controlled BFF exposes the matching exact paths under `/api/backend/`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `agencies/` | Scoped list, counts, search and optional `active=true/false` filter; defaults to all statuses |
| POST | `agencies/` | Create name/code/status; active defaults to true |
| GET | `agencies/{id}/` | Scoped information, counts, accountant names, ten recent sheets and safe recent audit events |
| PATCH | `agencies/{id}/` | Edit name/code; changed code requires `confirm_code_change: true` |
| GET | `agencies/{id}/impact/` | Scoped lifecycle impact counts |
| POST | `agencies/{id}/deactivate/` | Requires reason, `confirmed: true`, and `acknowledge_editable_sheets: true` when applicable |
| POST | `agencies/{id}/reactivate/` | Requires reason and `confirmed: true` |

PUT and DELETE are not agency operations. The BFF does not accept arbitrary actions, suffixes, or methods.

## Permissions and lifecycle rules

- Super Admin alone can create/edit/deactivate/reactivate. Accountant mutation requests return 403, and mutation UI is absent for accountants.
- Accountants can list/read only assigned agencies, including inactive agencies. Detail and impact requests outside their scope return 404. Summary queries are anchored to the selected agency. Recent audit events respect existing history permission and terminal-history restrictions.
- Name/code inputs are trimmed and required; uniqueness is case-insensitive. Codes use 1-40 ASCII letters, digits, underscores or hyphens (`^[A-Za-z0-9_-]+$`). Duplicate responses identify the relevant field; database exception details are not returned.
- PATCH cannot change active status. Code edits require explicit acknowledgement and explain preservation of existing snapshots.
- Deactivation preserves child records and their individual states. It blocks daily-sheet writes and workflow changes, all three Excel import types (including confirmation of old previews), new people/Sub-Agent Numbers/Terminal Numbers, dependent activation, terminal mutations/reassignment, and new accountant assignments through both assignment APIs.
- Draft/Returned/Reopened sheets are counted and require acknowledgement; they are neither deleted nor submitted.
- Reactivation updates only the agency. It does not alter dependent statuses or assignment permission flags.
- Historical reads remain scoped and available. Reports/export retain the existing Super Admin-only policy and now accept inactive agencies. Games and weekly schedules are global, not agency-owned; sheet-game activity is governed by the sheet's agency checks.
- Four immutable agency audit actions store allowlisted agency identity, old/new values, actor ID, reason, impact counts and the existing automatic timestamp. Detail responses expose action/timestamp only, not arbitrary audit payloads or credentials.
- Agency-dependent API writers use transactions and deterministic parent row locks, consistent with the existing register lock order. Repeated status transitions return 409 instead of emitting duplicate audit events.

## Migration

`backend/core/migrations/0013_alter_auditlog_action_agency_agency_name_ci_unique_and_more.py` adds database `Lower(name)` and `Lower(code)` unique constraints and registers the four agency audit action choices. It does not replace agencies, rewrite snapshots, or alter relationships.

The migration ran only in isolated test databases. It has not been applied to the configured application database. Existing case-only duplicate names/codes would need resolution before applying the constraints; no automatic merge or deletion is performed.

## Changed implementation files

| File | Change |
| --- | --- |
| `backend/core/agencies.py` | Shared lifecycle, active-agency checks, counts, locks and audit helpers |
| `backend/core/views.py` | Existing agency endpoints and dependent API enforcement |
| `backend/core/serializers.py` | Agency field validation, confirmation and assignment validation |
| `backend/core/models.py` | Case-insensitive constraints and audit action choices |
| `backend/core/admin.py` | Read-only agency admin; no hard deletion |
| `backend/core/reports.py` | Historical reporting for inactive agencies |
| `backend/core/terminal_register.py` | Inactive-agency enforcement and preview locking |
| `backend/core/migrations/0013_alter_auditlog_action_agency_agency_name_ci_unique_and_more.py` | Schema migration |
| `backend/core/tests/test_agency_management.py` | Permissions, lifecycle, imports, preservation, uniqueness and concurrency coverage |
| `frontend/components/AgenciesClient.js` | Agency management screen and dialogs |
| `frontend/lib/agency-operations.js` | Filtering and confirmation rules |
| `frontend/lib/controlled-proxy-path.js` | Exact agency path/method allowlist |
| `frontend/app/dashboard/agencies/page.js` | Replace placeholder |
| `frontend/app/dashboard/assigned-agencies/page.js` | Accountant read-only entry point |
| `frontend/app/globals.css` | Bounded responsive cards, counts and status styling |
| `frontend/tests/agency-management.test.mjs` | Rendered component interactions and proxy tests |
| `frontend/tests/agency-layout.mjs` | Actual Chromium viewport checks |

This report and `agency-*-verification.txt` are new verification artifacts. The changes shown in `docs/system-documentation.md` and `docs/training-manual.md`, and the other existing untracked files, predate this task and were untouched.

## Verification

All Django commands used `--settings=config.test_settings`, which points exclusively to an isolated in-memory SQLite database.

| Check | Result |
| --- | --- |
| `python manage.py makemigrations --check` | Pass; no changes detected |
| `python manage.py check` | Pass; no issues |
| Complete Django suite | 192 tests: 191 passed, 1 skipped |
| Complete frontend suite (`npm test`) | 112 passed |
| `npm run lint` | Pass |
| `npm run build` | Pass; production routes generated |
| `git diff --check` | Pass |
| Chromium layout checks | 15 passed: list/create/edit/deactivate/reactivate at 390, 768 and 1440 pixels, with long identifiers |

The skipped test exercises simultaneous PostgreSQL-style row-locking transitions. SQLite has no `SELECT FOR UPDATE` support; the test is included for execution with an isolated row-lock-capable test database. Actual PostgreSQL concurrency behavior was not exercised here. Django also emits its existing missing-local-staticfiles warning; its intentional import-failure test emits a safe failure reference.

The in-app browser tool could not connect because of a sandbox metadata error. Layout verification instead used installed headless Chromium against rendered components and production CSS. Interaction tests use the project's React component harness; this was not a live authenticated browser walkthrough.

## Full git status

```text
On branch main
Your branch is up to date with 'origin/main'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   backend/core/admin.py
	modified:   backend/core/models.py
	modified:   backend/core/reports.py
	modified:   backend/core/serializers.py
	modified:   backend/core/terminal_register.py
	modified:   backend/core/views.py
	modified:   docs/system-documentation.md
	modified:   docs/training-manual.md
	modified:   frontend/app/dashboard/agencies/page.js
	modified:   frontend/app/dashboard/assigned-agencies/page.js
	modified:   frontend/app/globals.css
	modified:   frontend/lib/controlled-proxy-path.js

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	agency-django-verification.txt
	agency-frontend-verification.txt
	agency-layout-verification.txt
	agency-management-report.md
	backend/core/agencies.py
	backend/core/migrations/0013_alter_auditlog_action_agency_agency_name_ci_unique_and_more.py
	backend/core/tests/test_agency_management.py
	django-final-tests.txt
	django-test-output.txt
	django-verification.txt
	frontend-test-output.txt
	frontend/components/AgenciesClient.js
	frontend/lib/agency-operations.js
	frontend/tests/agency-layout.mjs
	frontend/tests/agency-management.test.mjs
	"s -ExecutionPolicy RemoteSigned) ; (& e\357\200\272Treasureland_investmentbackend.venvScriptsActivate.ps1)"
	sub-agent-django-final.txt
	terminal-test-output.txt

no changes added to commit (use "git add" and/or "git commit -a")
```
