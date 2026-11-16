# Confirmed weekly schedule update

Implemented locally; no commit, push, deployment, production seeding, or production record access. The working tree was clean when work began. Verification used `config.test_settings`, which explicitly selects an isolated in-memory SQLite database.

## Design and historical protection

Previously, Whole Day status also identified Ghana games. Double Chance makes that ambiguous. `WeeklyGameSchedule.category` now explicitly distinguishes `TIMED`, `GHANA`, and `DOUBLE_CHANCE`. Model and serializer validation require category and Whole Day status to agree. The existing database uniqueness constraint on active game/day pairs remains in place; it is stronger than uniqueness within a category.

The catalogue game named **Ghana Game** is a separate `TIMED` game; it must not use the `GHANA` Whole Day category. The approved 7/6 weekday counts remain unchanged. Since the current schedule is full, a Super Admin must explicitly deactivate a timed assignment before adding Ghana Game to that weekday; the application does not select or replace a game automatically. Weekday and closing/draw times are entered explicitly in Africa/Accra.

New Daily Sheet games copy category alongside the existing game ID, displayed name, Whole Day flag, closing/draw times, display order, and holiday flag. `category_snapshot` is nullable for legacy snapshots: no historical classification is inferred or backfilled. Re-running snapshot creation on a populated sheet returns without changing it.

Holiday validation and effective schedules select GHANA explicitly. Legacy override references to Monday Special or Lucky G resolve to the canonical Ghana schedule without rewriting override records. Double Chance and timed games remain present. The frontend labels categories, uses Whole Day for both untimed categories, and restricts holiday choices to Ghana schedules.

Import preview and confirmation share the same category-aware effective schedule builder, including holidays. Existing-sheet previews created before categories were introduced can still confirm when their original fingerprint matches. Canonical header aliases resolve to the actual sheet snapshot name, preserving historical import names. The preview displays the entire applicable schedule, including games absent from workbook sales columns. Reports expose snapshot categories without recalculating historical values.

## Migrations

- `0022_game_categories`: additive schedule category and nullable DailySheetGame category snapshot fields.
- `0023_confirmed_weekly_schedule`: idempotently replaces legacy weekly references with canonical game records and adds Double Chance for every weekday. Existing Game names and IDs used by historical records are not renamed. Missing Ghana and Double Chance schedule rows are created; duplicate legacy candidates are deactivated before the retained row is repointed. Timed schedule rows, times, and display-order values are untouched. Double Chance shares the Ghana display-order position so they appear together.
- `0027_game_catalogue_and_schedule_constraints` remains atomic. After repairing display order it forces deferred PostgreSQL constraints to immediate, draining pending trigger events before index creation; the repair and constraint creation therefore roll back together on failure.
- The migration uses historical Django models and the migration connection alias. It does not call `seed_initial_data`, modify Daily Sheets, snapshots, transactions, sales, imports, overrides, or payment records. Its reverse data operation deliberately does not undo schedule data.
- Missing unrelated timed rows are not invented or repaired: counts below assume the existing timed schedule is intact.

## Final weekly schedule

| Day | Ghana game (Whole Day) | Additional Whole Day game | Timed games retained in their existing order | Active count |
| --- | --- | --- | --- | --- |
| Monday | MSP | Double Chance | Peoples, Bingo, Metro, International, Diamond | 7 |
| Tuesday | Lucky Ghana | Double Chance | 06, Jackpot, Club Master, Super, Gold | 7 |
| Wednesday | Midweek | Double Chance | Mark II, VAG, Enugu, Lucky, Tota | 7 |
| Thursday | Fortune | Double Chance | Fairchance, Diamond, International, Bingo, Peoples | 7 |
| Friday | Bonanza | Double Chance | Metro, Gold, Jackpot, VAG, Royal | 7 |
| Saturday | National | Double Chance | Super, Club Master, 06, Fairchance, King | 7 |
| Sunday | Aseda | Double Chance | Enugu, Lucky, Tota, Mark II | 6 |

## Financial safeguard

Commission remains **5%** (`0.05`); To Pay remains `0.95` of NET Sales. No financial formulas were changed. Regression coverage verifies NET Sales of 300, commission of 15, To Pay of 285, unchanged historical sheet totals, and an unchanged payment obligation of 285 across repeated migration runs. Historical snapshots and legacy Game names are compared before and after migration.

## Verification (initial implementation)

- Django system check: passed.
- Migration consistency (`makemigrations --check --dry-run`): passed, no changes detected.
- Focused schedule, category, holiday, Daily Sheet and import tests: 53 passed before the final additional full-legacy migration test.
- Final full Django suite: 262 tests, passed; 9 PostgreSQL/row-lock-dependent tests skipped under isolated SQLite.
- Frontend suite: 159 passed, no skips.
- ESLint: passed.
- Final Next.js production build: passed. A sandbox restriction on `.next/trace` required the authorized local build to run with elevated filesystem access.
- `git diff --check`: passed.
- Rendered component and responsive CSS assertions cover the schedule and Daily Sheet displays; no live mobile browser inspection was performed.
- No production database was migrated or accessed. Historical sheets were not rewritten. Test fixtures and temporary test databases are the only data used.

## Capacity concurrency follow-up (2026-11-16)

Schedule API writes and catalogue-game updates now acquire PostgreSQL transaction-level advisory locks for weekdays 1 through 7 in ascending order before serializer validation. The lock set covers empty weekdays as well as existing assignments, and remains held through the save and audit write. Capacity is therefore rechecked against committed state after competing schedule creation, reactivation, reassignment, game reactivation, or schedule seeding releases the lock. These low-volume configuration writes are serialized to keep weekday limits reliable.

Verification on a disposable local PostgreSQL 18 instance: **333 backend tests passed, 0 skipped**, including separate-connection competing requests for the last slot and overlapping schedule/game reactivation. Frontend: **203 tests passed**; ESLint and Next.js build passed. The PostgreSQL instance was stopped and removed after testing. No production data was accessed or changed.

## Changed files

Backend implementation: `backend/core/admin.py`, `game_schedule.py`, `holiday_overrides.py`, `importers.py`, `models.py`, `reports.py`, `serializers.py`, and `views.py`.

Migrations: `backend/core/migrations/0022_game_categories.py` and `0023_confirmed_weekly_schedule.py`.

Backend tests: `backend/core/tests/test_game_categories.py`, `test_game_schedule_update.py`, `test_schedule_capacity_postgresql.py`, `test_holiday_game_overrides.py`, `test_daily_sheet_imports.py`, `test_phase_1.py`, `test_phase_2.py`, `test_phase_4.py`, and `test_phase_5.py`. The phase fixtures explicitly isolate their custom schedules from migration-created schedule rows.

Frontend: `frontend/components/GameScheduleClient.js`, `DailySheetDetailClient.js`, `DailySheetImportClient.js`, `frontend/lib/game-schedule-operations.js`, `frontend/tests/auth-security.test.mjs`, and `game-categories.test.mjs`.

Report: `docs/confirmed-weekly-schedule-update.md`.
