import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../components/PaymentsClient.js", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

function section(start, end) {
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}

const payers = section("function Payers(", "function Obligations(");
const obligations = section("function Obligations(", "function PaymentSuccessBanner(");
const paymentSuccess = section("function PaymentSuccessBanner(", "function ObligationDetail(");
const paymentForm = section("function PaymentForm(", "function Receipt(");

test("payer creation closes only on success, refreshes the list, and reports non-sensitive details", () => {
  assert.match(payers, /const created = await clientRequest/);
  assert.match(payers, /setForm\(null\);\s*setSuccess\(\{ payer:/);
  assert.match(payers, /await onRefresh\(\)/);
  assert.match(payers, /Payer added successfully\./);
  for (const detail of ["Payer", "Agency", "Linked Sub-Agent Numbers", "Status"]) assert.match(payers, new RegExp(`<dt>${detail}<\\/dt>`));
  assert.match(payers, /View payer/);
  assert.match(payers, /Add another payer/);
  const successDetails = payers.slice(payers.indexOf("Payer added successfully."), payers.indexOf("<section className=\"payer-grid\""));
  assert.doesNotMatch(successDetails, /telephone|email|address|notes/i);
});

test("obligation creation refreshes the obligation list and analytics and reports required details", () => {
  assert.match(obligations, /const created = await clientRequest\(apiPath\("payment-obligations\/"\)/);
  assert.match(obligations, /setForm\(null\);\s*setSuccess\(\{ obligation:/);
  assert.match(obligations, /await onRefresh\(\)/);
  assert.match(source, /clientRequest\(apiPath\("payments\/analytics\/"\)\)/);
  assert.match(obligations, /Payment obligation created successfully\./);
  for (const detail of ["Obligation", "Payer", "Agency", "Description", "Expected amount", "Obligation date", "Status"]) {
    assert.match(obligations, new RegExp(`<dt>${detail}<\\/dt>`));
  }
  assert.match(obligations, /formatPaymentMoney\(success\.obligation\.total_expected\)/);
  assert.match(obligations, /View obligation/);
  assert.match(obligations, /Create another obligation/);
});

test("creation submit controls prevent duplicates and show processing labels", () => {
  assert.match(payers, /if \(pendingRef\.current\) return/);
  assert.match(payers, /disabled=\{pending\} aria-busy=\{pending\}>\{pending \? \(form\.id \? "Saving payer…" : "Adding payer…"\)/);
  assert.match(obligations, /if \(pendingRef\.current\) return/);
  assert.match(obligations, /pending \? "Creating obligation…"/);
  assert.match(paymentForm, /if \(pending \|\| pendingRef\.current\) return/);
  assert.match(paymentForm, /pending \? "Recording payment…"/);
});

test("payer, obligation, and payment failures preserve their forms and surface backend errors", () => {
  assert.match(payers, /catch \(failure\) \{\s*setError\(apiError\(failure\)\);/);
  assert.match(obligations, /catch \(failure\) \{\s*setError\(apiError\(failure\)\);/);
  assert.match(paymentForm, /catch \(failure\) \{ setError\(apiError\(failure\)\); setFields\(failure\?\.payload \|\| \{\}\); \}/);
  assert.match(source, /function apiError\(failure\)/);
  assert.match(source, /failure\?\.status < 500 && failure\?\.payload \? failure\.payload/);
  assert.doesNotMatch(payers, /catch \(failure\) \{[^}]*setForm\(null\)/s);
  assert.doesNotMatch(obligations, /catch \(failure\) \{[^}]*setForm\(null\)/s);
  assert.doesNotMatch(paymentForm, /catch \(failure\) \{[^}]*setForm\(EMPTY_PAYMENT\)/s);
});

test("payer and obligation create-another actions reopen clean forms", () => {
  assert.match(source, /setForm\(emptyPayer\(data\.agencies\[0\]\?\.id \|\| ""\)\)/);
  assert.match(source, /setForm\(emptyObligation\(data\.agencies\[0\]\?\.id \|\| ""/);
  assert.match(source, /function emptyPayer\(agency = ""\)/);
  assert.match(source, /function emptyObligation\(agency = "", payer = ""\)/);
});

test("record-payment success refreshes the obligation and analytics and hides the next-payment action when paid", () => {
  assert.match(paymentSuccess, /Payment recorded successfully\./);
  assert.match(paymentSuccess, /Amount received/);
  assert.match(paymentSuccess, /Receipt number/);
  assert.match(paymentSuccess, /Total paid/);
  assert.match(paymentSuccess, /Remaining balance/);
  assert.match(paymentSuccess, /Obligation status/);
  assert.match(paymentSuccess, /Obligation fully paid\./);
  assert.match(paymentSuccess, /canRecord && outstanding \? .*Record another payment/);
  assert.match(source, /if \(view === "obligations" \|\| view === "obligation"\)/);
  assert.match(source, /data\.analytics = await clientRequest\(apiPath\("payments\/analytics\/"\)\)/);
  assert.match(source, /await onRefresh\(\);\s*setSuccess\(payment\)/);
  assert.match(source, /Download receipt/);
});

test("record-payment action from the new obligation banner is permission-gated", () => {
  assert.match(obligations, /const successCanRecord = success && \(user\.role === "SUPER_ADMIN" \|\| user\.agency_assignments\?\.some/);
  assert.match(obligations, /\{successCanRecord \? <Link[^>]*>Record payment<\/Link> : null\}/);
  assert.match(source, /new URLSearchParams\(window\.location\.search\)\.get\("record"\) === "1"/);
});

test("success banners announce status, receive keyboard focus, and keep actions mobile-usable", () => {
  assert.match(source, /role="status" aria-live="polite" tabIndex=\{-1\}/);
  assert.match(source, /ref\.current\?\.focus\(\)/);
  assert.match(source, /Dismiss success message/);
  assert.match(css, /\.payment-success-actions \{ margin-top:/);
  assert.match(css, /\.payment-success-actions \{ align-items: stretch; flex-direction: column; \}/);
  assert.match(css, /\.payment-success-actions > \.primary-button, \.payment-success-actions > \.secondary-button \{ width: 100%; justify-content: center; \}/);
});

test("success feedback is page-local and is not persisted across navigation or reloads", () => {
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
  assert.match(payers, /const \[success, setSuccess\] = useState\(null\)/);
  assert.match(obligations, /const \[success, setSuccess\] = useState\(null\)/);
});
