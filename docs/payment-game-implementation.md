# Game-linked Payment Obligations

## Existing relationship and design

Payment Obligations previously referenced an agency, payer and optional Sub-Agent Number, with number/identity snapshots. They had no game relationship. Payments referenced an obligation and retained financial and identity snapshots.

New API-created obligations require an agency, payer, active assigned number, business date, explicit effective game, description and positive total expected. The backend uses the existing effective schedule resolver, including explicit TIMED, GHANA and DOUBLE_CHANCE categories and Ghana-only Holiday Override replacement. Date-only input represents the Africa/Accra business day; no browser-time-based game selection occurs.

The payment system remains independent of DailySheet and DailySheetGame. Game snapshots include game ID/name/category, business date/ISO weekday, Whole Day/times, holiday status/name/ID and original game/source date. Payments copy the obligation snapshot, including for later partial payments. Model saves and queryset bulk mutation guards protect the new identity fields. Receipt rendering and analytics use stored snapshots.

## Migration

`backend/core/migrations/0025_payment_game_snapshots.py` depends on the existing uncommitted commission migration 0024. It adds nullable obligation game FK, business date, immutable game ID and JSON snapshot, optional unique creation key, and a nullable payment JSON snapshot. It adds an agency/date/game index, a complete-or-legacy identity check, and a database unique constraint on agency/number/business date/game ID snapshot.

There is no data backfill or historical game inference. Migration tests compare every existing obligation/payment column before and after migration and verify reversal preserves those rows. Earlier migrations were not edited. Reversing 0025 removes the newly added game metadata, so it should only be reversed before relying on new game-linked records.

## API and permissions

- `GET /api/agencies/{agency_id}/payment-effective-games/?business_date=YYYY-MM-DD`: authenticated, agency-scoped, exact ISO date, deterministic order; rejects extra/repeated query parameters and returns selector display fields only. The frontend proxy permits this exact numeric-agency path with GET only.
- `POST /api/payment-obligations/`: accepts `game`, `business_date` and optional `creation_key` alongside existing fields. Creates snapshots on the backend. Identical same-actor request keys replay the existing obligation; conflicting reuse is rejected without disclosing another obligation. Existing register/number/payer locks serialize creation and the database constraint supplies a final duplicate safeguard.
- Payment creation rejects submitted game/date/snapshot fields. Its existing payment idempotency, amounts, receipt numbering, locks and reversal rules remain intact.
- Obligation and payment lists accept game ID/name/category, business date/range, weekday and Holiday Override filters. Payment/obligation status and payment-date filters remain agency-scoped.
- Analytics add `game_breakdown`, with expected/gross/reversals/net/outstanding/counts/last-payment values. `group_by` supports game, category, business_date, weekday, agency, payer, sub_agent_number and terminal_number. Game pagination uses `game_page`, independently of number pagination's `page`.

Super Admin retains access to all agencies. Accountant creation requires the selected agency's `can_create`; read-only assignments cannot create obligations or payments. Agency number discovery is now readable within an authorized agency so create-only accountants can find existing numbers; quick-create register editing still requires `can_edit`. Schedule/Holiday Override administration permissions are unchanged.

## Duplicate and cancellation policy

A second obligation for the same agency/number/business date/effective game is rejected with a linkable existing obligation ID and a clear instruction to record payment against it. Cancelled identities remain reserved: replacement is explicitly prohibited, rather than silently overwriting or reusing them. Existing cancellation remains audited. Creation audit metadata contains safe IDs, business date, actor and timestamp; no names, notes or request payloads are added.

## UI and receipts

The New Obligation flow selects agency, saved number/terminal, business date and then a backend-provided game. Choices display category, Whole Day/times and Holiday Override labels; a selected-game review appears before submission. Changes of agency/date clear the game. Loading, empty and retry states prevent accidental selection. Existing failed-form preservation and double-submit protection remain.

Obligation lists/details, payment history, payment forms and HTML/PDF receipts show stored game details. Legacy records explicitly display `Game: Not assigned - legacy obligation.` and remain payable/reversible/downloadable. Global payment history and game analytics provide scoped filters and pagination.

## Release manifest

The following 39 repository-relative paths are the complete approved release scope, including this report. The 17 previously preserved files were reviewed individually: their diffs contain only the 2% commission change, historical-rate preservation, import/report compatibility, matching security/compatibility test assertions and related documentation. No implementation in those 17 files was changed during release preparation.

- `backend/README.md`
- `backend/core/importers.py`
- `backend/core/migrations/0024_daily_sheet_commission_snapshot.py`
- `backend/core/migrations/0025_payment_game_snapshots.py`
- `backend/core/models.py`
- `backend/core/payment_games.py`
- `backend/core/payment_numbers.py`
- `backend/core/reports.py`
- `backend/core/serializers.py`
- `backend/core/tests/test_commission.py`
- `backend/core/tests/test_daily_sheet_imports.py`
- `backend/core/tests/test_game_categories.py`
- `backend/core/tests/test_payment_games.py`
- `backend/core/tests/test_payment_numbers.py`
- `backend/core/tests/test_phase_2.py`
- `backend/core/tests/test_phase_4.py`
- `backend/core/tests/test_phase_5.py`
- `backend/core/tests/test_sheet_safety.py`
- `backend/core/tests/test_tpm_reassignment.py`
- `backend/core/urls.py`
- `backend/core/views.py`
- `docs/payment-game-implementation.md`
- `docs/system-documentation.md`
- `docs/training-manual.md`
- `frontend/components/DailySheetDetailClient.js`
- `frontend/components/DailySheetImportClient.js`
- `frontend/components/DailySheetsClient.js`
- `frontend/components/PaymentGamePicker.js`
- `frontend/components/PaymentsClient.js`
- `frontend/components/ReportsClient.js`
- `frontend/lib/controlled-proxy-path.js`
- `frontend/lib/payment-games.js`
- `frontend/lib/phase4-operations.js`
- `frontend/tests/auth-security.test.mjs`
- `frontend/tests/commission-policy.test.mjs`
- `frontend/tests/payment-game-layout.mjs`
- `frontend/tests/payment-games.test.mjs`
- `frontend/tests/payment-numbers.test.mjs`
- `frontend/tests/payment-success-feedback.test.mjs`

Migration order remains 0023 ? 0024 ? 0025. Migration 0024 adds a historical 0.0500 rate snapshot without rewriting existing financial columns, then sets the default for new sheets to 0.0200. Migration 0025 is additive and leaves legacy obligation/payment game fields null. The payment and commission implementations, tests and other documentation are preserved exactly as reviewed.

The pre-release source review found no unrelated changes, production data, credentials or generated artifacts in this manifest. Database tests use disposable in-memory SQLite; existing fixture helpers operate only within that test database. Release verification results below distinguish skipped PostgreSQL concurrency tests from executed tests. No production business records may be manually changed during this release.

## Verification

Release verification rerun on 2026-11-13 matched the results below. Only this report was edited during release preparation; all 38 other release-file hashes remained unchanged. PostgreSQL-only tests were skipped, not run or counted as passed.

- Django system check: passed.
- Migration consistency (`makemigrations --check --dry-run`, isolated settings): passed; no missing migrations.
- Focused payment, receipt, analytics, schedule, holiday, migration and commission regression suite: 89 tests, passed with 2 PostgreSQL-only skips.
- Full Django suite: 281 tests, passed with 10 PostgreSQL-only skips (271 executed).
- All frontend tests: 173 passed.
- ESLint: passed.
- Next.js production build: passed. An initial filesystem permission error was resolved by running the authorized build with local filesystem access; configuration was not changed.
- Chromium mobile/layout and keyboard checks: 21 scenarios passed at 390, 768 and 1440 pixels across game selector and existing number picker states; no overflow.
- Repository diff reviewed; `git diff --check` passed. The release manifest includes the preserved work and this feature; staged scope and final status will be checked again before commit/push.

The approved isolated local PostgreSQL endpoint `127.0.0.1:5433` was unavailable. PostgreSQL concurrency tests, including the new simultaneous duplicate-obligation test, were not executed. No remote database was substituted. Database uniqueness was independently verified on SQLite, but PostgreSQL lock/concurrency behavior still needs that isolated test run.

Daily Sheet commission remains 2%; existing historical commission snapshots retain their prior rates. Historical obligations, payment receipts and audit records were not rewritten or assigned inferred games. No migration was applied to a persistent application database.
