import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function file(path) {
  return readFile(new URL(`../${path}`, import.meta.url), "utf8");
}

test("payments overview exposes discoverable quick actions with correct routes", async () => {
  const source = await file("components/PaymentsClient.js");
  assert.match(source, /function QuickActions\(\{ user \}\)/);
  assert.match(source, /<QuickActions user=\{user\} \/>/);
  assert.match(source, /Manage payers/);
  assert.match(source, /New obligation/);
  assert.match(source, /View obligations/);
  assert.match(source, /Payment analytics/);
  assert.match(source, /href="\/dashboard\/payments\/payers\?create=1"/);
  assert.match(source, /href="\/dashboard\/payments\/payers">Manage payers/);
  assert.match(source, /href="\/dashboard\/payments\/obligations\?create=1"/);
  assert.match(source, /href="\/dashboard\/payments\/obligations">View obligations/);
  assert.match(source, /href="\/dashboard\/payments\/analytics">Payment analytics/);
});

test("workflow hint guides payer creation before obligations", async () => {
  const source = await file("components/PaymentsClient.js");
  assert.match(source, /Create or select a payer before creating a payment obligation\./);
});

test("quick action creation controls are gated by the same backend can_create flag as the destination pages", async () => {
  const source = await file("components/PaymentsClient.js");
  const quickActionsBlock = source.slice(source.indexOf("function QuickActions"), source.indexOf("function Overview"));
  assert.match(quickActionsBlock, /const canManage = user\.role === "SUPER_ADMIN" \|\| user\.agency_assignments\?\.some\(\(item\) => item\.can_create\);/);
  assert.match(quickActionsBlock, /\{canManage \? <Link className="primary-button" href="\/dashboard\/payments\/payers\?create=1">/);
  assert.match(quickActionsBlock, /\{canManage \? <Link className="primary-button" href="\/dashboard\/payments\/obligations\?create=1">/);
  // Manage/View/Analytics navigation links are always rendered (unconditional), so restricted
  // users still get read access while Add/New stay tied to the backend-enforced can_create flag.
  assert.doesNotMatch(quickActionsBlock, /\{canManage \? <Link className="secondary-button" href="\/dashboard\/payments\/payers">/);
  assert.doesNotMatch(quickActionsBlock, /\{canManage \? <Link className="secondary-button" href="\/dashboard\/payments\/analytics">/);
});

test("Super Admin qualifies for management quick actions regardless of agency assignments", async () => {
  const source = await file("components/PaymentsClient.js");
  const quickActionsBlock = source.slice(source.indexOf("function QuickActions"), source.indexOf("function Overview"));
  assert.match(quickActionsBlock, /user\.role === "SUPER_ADMIN"/);
});

test("create-panel auto-open on destination pages is guarded and never bypasses the Add\\/Create button", async () => {
  const source = await file("components/PaymentsClient.js");
  assert.match(source, /canCreate && typeof window !== "undefined" && new URLSearchParams\(window\.location\.search\)\.get\("create"\) === "1"/g);
  // Add payer / Create obligation buttons remain visible on the destination pages independent of the query param.
  assert.match(source, /Add payer<\/button> : null\}/);
  assert.match(source, /Create obligation<\/button> : null\}/);
});

test("quick action layout uses reliable route links with mobile-safe wrapping", async () => {
  const source = await file("components/PaymentsClient.js");
  const css = await file("app/globals.css");
  assert.doesNotMatch(source, /useSearchParams/);
  assert.match(css, /\.payment-quick-actions \{ min-width: 0; max-width: 100%;/);
  assert.match(css, /\.quick-action-row \{ display: flex; flex-wrap: wrap;/);
  assert.match(css, /\.quick-action-row \{ flex-direction: column; align-items: stretch; \}/);
});

test("payment routes remain gated behind dashboard authentication", async () => {
  const routes = await Promise.all([
    file("app/dashboard/payments/page.js"),
    file("app/dashboard/payments/payers/page.js"),
    file("app/dashboard/payments/obligations/page.js"),
    file("app/dashboard/payments/analytics/page.js"),
  ]);
  assert.equal(routes.every((sourceText) => sourceText.includes("requireDashboardUser")), true);
});
