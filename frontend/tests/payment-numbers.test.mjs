import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { isAllowedBackendProxyPath } from "../lib/controlled-proxy-path.js";
import { analyticsQuery } from "../lib/payment-operations.js";

const picker = await readFile(new URL("../components/PaymentNumberPicker.js", import.meta.url), "utf8");
const ledger = await readFile(new URL("../components/PaymentNumberLedger.js", import.meta.url), "utf8");
const payments = await readFile(new URL("../components/PaymentsClient.js", import.meta.url), "utf8");
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

test("payment number proxy routes allow only exact scoped methods", () => {
  for (const method of ["GET", "POST"]) assert.equal(isAllowedBackendProxyPath("agencies/5/payment-numbers/", method), true);
  for (const path of ["agencies/payment-numbers", "agencies/5/payment-numbers/7", "agencies/5/payment-numbers/reassign", "payment-numbers"]) assert.equal(isAllowedBackendProxyPath(path, "POST"), false);
  for (const method of ["PATCH", "PUT", "DELETE"]) assert.equal(isAllowedBackendProxyPath("agencies/5/payment-numbers/", method), false);
  assert.equal(isAllowedBackendProxyPath("payment-payers/7/numbers/", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("payment-payers/7/numbers/", "POST"), false);
});

test("number and terminal filters are sent to authoritative analytics", () => {
  const params = new URLSearchParams(analyticsQuery({ agencies: ["1", "2"], payer: "5", sub_agent_number_snapshot: "SUB-A", terminal_number: "TERM-A", obligation_status: "OPEN", payment_method: "CASH", recorded_by: "3", payment_start: "2026-11-01" }));
  assert.deepEqual(params.getAll("agency"), ["1", "2"]);
  assert.equal(params.get("terminal_number"), "TERM-A");
  assert.equal(params.get("sub_agent_number_snapshot"), "SUB-A");
  assert.match(payments, /NumberTotalsTable rows=\{result\?\.number_breakdown\?\.results/);
  assert.match(ledger, /sub_agent_number: number.id, payer/);
});

test("picker debounces bounded scoped searches and discards stale responses", () => {
  assert.match(picker, /}, 300\)/);
  assert.match(picker, /cancelled = true; clearTimeout\(timer\)/);
  assert.match(picker, /if \(!cancelled\) setState/);
  assert.match(picker, /agencies\/\$\{agency\}\/payment-numbers/);
  assert.match(picker, /payment-payers\/\?agency=\$\{agency\}&active=true/);
  assert.doesNotMatch(picker, /tpm-codes|terminal-numbers\//);
  assert.match(picker, /page_size=20/);
});

test("new obligation requires explicit selection and labels legacy and receipt snapshots", () => {
  assert.match(payments, /disabled=\{pending \|\| !form.sub_agent_number\}/);
  assert.match(payments, /sub_agent_number: number\?\.id/);
  assert.match(payments, /Legacy — Sub-Agent Number not assigned/);
  assert.match(payments, /Sub-Agent Number: Not assigned — legacy obligation\./);
  assert.match(payments, /NumberIdentity record=\{payment\} receipt/);
  assert.match(payments, /PayerNumberLedger payer=\{payer.id\}/);
});

test("quick-create preserves failures, prevents duplicate submissions, and focuses success", () => {
  assert.match(picker, /if \(pendingRef.current/);
  assert.match(picker, /catch \(failure\) \{ setError\(safeError\(failure\)\); \}/);
  assert.match(picker, /setQuick\(null\); setPayer\(null\); setPayerSearch\(""\); setSearch\(""\); setSuccess\(true\); onSelect\(created\)/);
  assert.match(picker, /successRef.current\?\.focus\(\)/);
  assert.match(picker, /role="status" aria-live="polite"/);
  assert.match(picker, /aria-pressed=\{value\?\.id === row.id/);
  assert.match(css, /\.payment-number-results button[^}]*white-space: normal/);
  assert.match(css, /\.payment-number-picker :focus-visible/);
});
