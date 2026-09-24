import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "../lib/controlled-proxy-path.js";
import { createPaymentIdempotencyKey, formatGhanaMoney, paymentFingerprint } from "../lib/payment-operations.js";

async function file(path) {
  return readFile(new URL(`../${path}`, import.meta.url), "utf8");
}

test("payment proxy allowlist is exact and method restricted", () => {
  assert.equal(isAllowedBackendProxyPath("payment-payers", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("payment-payers", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("payment-payers/7", "PATCH"), true);
  assert.equal(isAllowedBackendProxyPath("payment-payers/7/reassign_sub_agent", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("payment-obligations/7/cancel", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("payer-payments/7/reverse", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("payments/analytics", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("payer-payments/7/receipt", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("payer-payments/7/receipt", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("payments/analytics", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("accountants/7/reverse", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("payment-payers/7/unknown", "POST"), false);
  assert.equal(isBinaryBackendProxyPath("payer-payments/7/receipt", "GET"), true);
  assert.equal(isBinaryBackendProxyPath("payer-payments/7/receipt", "POST"), false);
});

test("payment routes and role-aware controls are present", async () => {
  const routes = await Promise.all([
    file("app/dashboard/payments/page.js"),
    file("app/dashboard/payments/payers/page.js"),
    file("app/dashboard/payments/payers/[id]/page.js"),
    file("app/dashboard/payments/obligations/page.js"),
    file("app/dashboard/payments/obligations/[id]/page.js"),
    file("app/dashboard/payments/receipts/[id]/page.js"),
    file("app/dashboard/payments/analytics/page.js"),
  ]);
  assert.equal(routes.every((source) => source.includes("requireDashboardUser")), true);
  const source = await file("components/PaymentsClient.js");
  assert.match(source, /Reverse|Reassign|Cancel obligation/);
  assert.match(source, /user\.role === "SUPER_ADMIN"/);
  assert.match(source, /can_create|can_edit|can_delete/);
  assert.match(source, /POSTED|REVERSED/);
  assert.match(source, /Download receipt/);
});

test("payment attempts use retry-stable idempotency keys without browser persistence", async () => {
  const source = await file("components/PaymentsClient.js");
  const operations = await file("lib/payment-operations.js");
  assert.match(source, /keyRef\.current/);
  assert.match(source, /paymentFingerprint/);
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
  assert.doesNotMatch(operations, /localStorage|sessionStorage/);
  const first = createPaymentIdempotencyKey();
  const second = createPaymentIdempotencyKey();
  assert.notEqual(first, second);
  assert.notEqual(paymentFingerprint({ amount_received: "10.00" }), paymentFingerprint({ amount_received: "11.00" }));
});

test("receipt and error handling preserve binary download behavior", async () => {
  const source = await file("components/PaymentsClient.js");
  const proxy = await file("lib/controlled-proxy-path.js");
  assert.match(source, /clientDownload/);
  assert.match(source, /URL\.createObjectURL/);
  assert.match(source, /URL\.revokeObjectURL/);
  assert.equal(proxy.includes("payer-payments\\/\\d+\\/receipt"), true);
  assert.match(source, /ErrorBox/);
});

test("analytics labels and responsive containment contracts exist", async () => {
  const source = await file("components/PaymentsClient.js");
  const css = await file("app/globals.css");
  assert.match(source, /Gross posted/);
  assert.match(source, /Reversed/);
  assert.match(source, /Net collected/);
  assert.match(source, /Obligation dates filter the portfolio/);
  assert.match(source, /payment_start/);
  assert.match(css, /payment-table-wrap/);
  assert.match(css, /overflow-x: auto/);
  assert.match(css, /max-width: 600px/);
  assert.match(css, /max-width: 980px/);
  assert.equal(formatGhanaMoney(1234.56), "GH₵ 1,234.56");
});

test("dashboard navigation exposes Payments only to permitted roles", async () => {
  const source = await file("components/DashboardShell.js");
  assert.match(source, /label: "Payments"/);
  assert.match(source, /user\.agency_assignments\?\.length/);
});
