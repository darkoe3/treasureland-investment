# Payment obligations by Sub-Agent Number

Implemented locally on 3 November 2026. No commit, push, deployment, production connection, or production data changes were performed. The initial working tree was clean. Existing migrations were not edited. Database verification used the isolated, in-memory `config.test_settings` database; fixture/seed commands invoked by existing tests ran only there.

## Relationships and decisions

- `Agency` owns `Person` records; `TPMCode` is the existing compatibility model for a Sub-Agent Number and belongs to a `Person`.
- `TerminalNumber` belongs to a `TPMCode`, with matching agency and person. Existing database constraints enforce case-insensitive terminal/code uniqueness and one active terminal per number.
- Payments use a separate `PaymentPayer`. `PayerSubAgentAssignment` links that payer to numbers, with one active payer assignment per number.
- `PaymentObligation` previously belonged only to a payer and agency. It now optionally references `TPMCode` at database level, while new API requests require an explicitly selected, eligible number. `PayerPayment` continues to reference its obligation.
- As explicitly approved, quick creation can create a register `Person` from the selected existing payer's saved details. A nullable `PaymentPayer.register_person` link records that identity. An existing unambiguous ownership link is reused; no person is matched by name, and typed search text never creates a payer.
- Historical obligations receive no guessed assignments or populated identity snapshots. They remain payable, reversible and reportable under the established rules, and display the legacy label.
- New obligations capture number, terminal, payer name/ID and agency name/ID. Payments copy that identity from the obligation, rather than reading the payer's current number assignments. Receipts use payment snapshots. Identity cannot be edited through the serializers; model validation also rejects changes, including after payment reversal.
- Payment numbering, posting idempotency, balance arithmetic, reversal permissions and gross/reversal/net distinctions are retained. Portfolio outstanding totals use all currently posted payments even when collection filters select only a subset of payments.

## API and permission rules

| Method and path | Behavior |
| --- | --- |
| `GET /api/agencies/{agency_id}/payment-numbers/?search=...` | Searches number, terminal and payer name in the selected agency. Terminal matches resolve to their owning number. Results include eligibility, identity, outstanding totals and open counts. Empty searches return no records. |
| `POST /api/agencies/{agency_id}/payment-numbers/` | Atomically creates a number, terminal and payer assignment. Requires `payer`, `sub_agent_number`, `terminal_number` and `confirmed: true`. An optional body `agency` must match the URL. |
| `GET /api/payment-payers/{payer_id}/numbers/` | Paginated payer number list, including inactive/historical assignments and their financial totals. |
| `GET /api/payment-obligations/` | Adds `sub_agent_number` (record ID), `sub_agent_number_snapshot` (text) and `terminal_number` filters; search now includes the number and terminal snapshots. Existing agency, payer, status, obligation-number and date filters remain. |
| `POST /api/payment-obligations/` | Requires `sub_agent_number`; revalidates eligibility under the register lock and records an ID-only creation audit event. |
| `GET /api/payer-payments/` | Adds number/terminal filters for number-specific payment history. Existing payer/agency/date filters remain. |
| `GET /api/payments/analytics/` | Adds the same number filters and a paginated `number_breakdown`, with expected, gross, reversals, net, outstanding, counts and last payment. Existing payer, agency, obligation status/date, payment method/date and recorder filters still apply. |

Number search/creation requires an active agency and agency `can_edit` for accountants. Super Admin can act across agencies, but inactive records cannot be selected or created against. Read-only agency access cannot create numbers. Payer creation and obligation/payment creation retain their existing `can_create` requirements. Number history and analytics retain existing agency read restrictions; recorder filtering retains its existing Super Admin restriction. No Terminal Register management or reassignment permissions were broadened.

New number endpoints default to 20 results and cap pages at 50, use deterministic ordering, and limit search text to 100 characters. Existing obligation/payment endpoints retain their existing bounded pagination. The controlled proxy adds only the exact agency-number GET/POST path and payer-number GET path.

Quick creation uses the existing deterministic agency-parent register locks, locks the selected payer, and runs creation plus audit events in one transaction. Existing case-insensitive database constraints remain the final duplicate protection. Duplicate requests reject rather than silently reassign. Same-agency duplicate errors identify the existing owner; cross-agency duplicate errors deliberately do not disclose another agency's payer details.

The two new creation audit actions are `PAYMENT_NUMBER_CREATED` and `PAYMENT_TERMINAL_CREATED`; their source is `PAYMENT_QUICK_CREATE`. Obligation creation uses the existing `PAYMENT_OBLIGATION_CREATED` action. New metadata contains record IDs and an operation source; actor and timestamp are also recorded by the immutable audit model. Names, notes, contact details and request payloads are excluded.

## Migration

`backend/core/migrations/0021_payerpayment_agency_id_snapshot_and_more.py` depends on existing migration `0020` and adds:

- Nullable obligation-to-number and payer-to-register-person foreign keys, both protected against deletion.
- Six obligation identity snapshot fields.
- Four payment snapshot fields; existing payment payer/agency name snapshots remain in use.
- Two audit action choices.

There is no data migration or assignment backfill. Existing records retain their original values; new nullable fields are null and new text fields are empty for those records. Django can reverse the schema additions, but rolling back after using the feature would discard the newly added identity columns and must not be treated as a lossless data rollback. The migration was exercised by test database creation and has not been applied to an operational database.

## Frontend behavior

The obligation dialog uses 300 ms debounced, agency-scoped backend searches with stale-response suppression and explicit selectable results. Quick creation uses a separately searched existing payer, confirmation checkbox and a separate Add Payer link to the existing workflow. Failures preserve values; pending guards prevent repeated submission. Success closes/resets quick creation, focuses an accessible status message and selects the returned number. Obligation success includes payer, both numbers, obligation number and expected amount.

Payer cards show number counts; payer detail has paginated number totals and number-specific receipt history. Obligation filtering is backend driven. Number analytics and receipt views display snapshot identity, and legacy obligations display the requested legacy wording. The obligation modal uses native modal focus handling. Long identifiers wrap at mobile widths.

## Verification

| Check | Result |
| --- | --- |
| Django system check, isolated settings | Passed; no issues |
| `makemigrations --check --dry-run`, isolated settings | Passed; no changes detected |
| Existing focused payment/terminal tests | 68 passed |
| Full Django suite, run from `backend` | 254 discovered: 245 passed, 9 skipped, no failures |
| All frontend tests | 156 passed |
| ESLint | Passed |
| Next.js production build | Passed |
| Real headless Chromium layout/focus checks | Search, quick-create and success states passed at 390, 768 and 1440 px; no horizontal overflow and controls/status feedback accept focus |
| `git diff --check` | Passed |

The frontend adds `jsdom` as a development-only dependency for real React DOM interaction tests. Existing payment-success tests retain their assertions; their import harness was extended for the new components.

PostgreSQL concurrency tests were **not executed**. The approved local test configuration points to loopback port `127.0.0.1:5433`, where no listener was available. SQLite was not used as a substitute for locking tests. Skipped coverage consists of:

- New simultaneous duplicate number/terminal creation test.
- Seven existing PostgreSQL payment tests: excess/valid concurrent payments, receipt/obligation numbering, identical/conflicting idempotency retries and simultaneous reversal.
- Existing agency test requiring `select_for_update` support.

Reproduce the principal checks from the repository root with the root `.venv`, using `backend` as the working directory for test discovery. Run the optional browser check from `frontend` after building:

```powershell
$env:CHROME_HEADLESS_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
node tests/payment-number-layout.mjs
```

## Changed files

- `backend/core/models.py`
- `backend/core/serializers.py`
- `backend/core/views.py`
- `backend/core/urls.py`
- `backend/core/payment_numbers.py` (new)
- `backend/core/migrations/0021_payerpayment_agency_id_snapshot_and_more.py` (new)
- `backend/core/tests/test_payment_numbers.py` (new)
- `frontend/components/PaymentsClient.js`
- `frontend/components/PaymentNumberPicker.js` (new)
- `frontend/components/PaymentNumberLedger.js` (new)
- `frontend/lib/controlled-proxy-path.js`
- `frontend/app/globals.css`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tests/payment-success-feedback.test.mjs`
- `frontend/tests/payment-numbers.test.mjs` (new)
- `frontend/tests/payment-number-interactions.test.mjs` (new)
- `frontend/tests/payment-number-layout.mjs` (new)
- `docs/payment-sub-agent-extension.md` (this report)

All implementation changes remain uncommitted. No old migration, Daily Sheet implementation, Terminal Register implementation or production record was modified.
