import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import { isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "../lib/controlled-proxy-path.js";
import { createPaymentIdempotencyKey, formatPaymentMoney, paymentFingerprint } from "../lib/payment-operations.js";
import { formatCurrency } from "../lib/currency.js";
import { moneyText } from "../lib/phase4-operations.js";
import { moneyText as reportMoneyText } from "../lib/report-operations.js";

async function file(path) {
  return readFile(new URL(`../${path}`, import.meta.url), "utf8");
}

async function sourceFiles(directory) {
  const entries = await readdir(new URL(`../${directory}/`, import.meta.url), { withFileTypes: true });
  const contents = await Promise.all(entries.map((entry) => {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) return sourceFiles(path);
    return entry.name.endsWith(".js") ? file(path) : null;
  }));
  return contents.flat().filter(Boolean);
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
  assert.equal(formatPaymentMoney(1234.56), "₦1,234.56");
});

test("shared NGN formatting is consistent across dashboard, Daily Sheet, reports and payments", () => {
  for (const formatter of [formatCurrency, moneyText, reportMoneyText, formatPaymentMoney]) {
    assert.equal(formatter(1250), "₦1,250.00");
    assert.equal(formatter(0), "₦0.00");
  }
});

test("active frontend source contains no legacy Ghana currency references", async () => {
  const legacyTerms = [
    `GH${String.fromCodePoint(0x20b5)}`,
    `G${"HS"}`,
    `GH${String.fromCodePoint(0x00a2)}`,
    `ce${"di"}`,
    `en-${"GH"}`,
  ];
  const legacyCurrency = new RegExp(legacyTerms.join("|"), "iu");
  const sources = (await Promise.all(["app", "components", "lib"].map(sourceFiles))).flat();
  for (const source of sources) assert.doesNotMatch(source, legacyCurrency);
});

test("dashboard navigation exposes Payments only to permitted roles", async () => {
  const source = await file("components/DashboardShell.js");
  assert.match(source, /label: "Payments"/);
  assert.match(source, /user\.agency_assignments\?\.length/);
});
