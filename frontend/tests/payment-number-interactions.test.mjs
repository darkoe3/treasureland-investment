import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import vm from "node:vm";
import { JSDOM } from "jsdom";
import * as money from "../lib/payment-operations.js";

const dom = new JSDOM("<!doctype html><body></body>", { url: "http://localhost", pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import("react");
const { createRoot } = await import("react-dom/client");
const require = createRequire(import.meta.url);
const source = await readFile(new URL("../components/PaymentNumberPicker.js", import.meta.url), "utf8");
const compiled = require("next/dist/build/swc").transformSync(source, { filename: "PaymentNumberPicker.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } }, target: "es2020" }, module: { type: "commonjs" } }).code;
let requests, handler, root, container;
const mod = { exports: {} };
vm.runInNewContext(compiled, { exports: mod.exports, module: mod, setTimeout, clearTimeout, URLSearchParams, require(name) {
  if (name === "next/link") return function TestLink({ children, ...props }) { return React.createElement("a", props, children); };
  if (name.includes("client-api")) return { apiPath: (path) => path, clientRequest: async (path, options) => { requests.push({ path, options }); return handler(path, options); } };
  if (name.includes("payment-operations")) return money;
  return require(name);
} });
const Picker = mod.exports.default;
const result = { id: 1, payer: 9, payer_name: "Existing payer", sub_agent_number: "SUB-1", terminal_number: "TERM-1", agency: 7, agency_name: "Agency", is_active: true, selectable: true, outstanding_balance: "40.00", open_obligation_count: 2 };
const wait = () => React.act(async () => { await new Promise((resolve) => setTimeout(resolve, 340)); });
async function mount(user = { role: "SUPER_ADMIN" }) {
  requests = []; container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  function Harness() { const [value, setValue] = React.useState(null); return React.createElement(Picker, { agency: 7, agencyName: "Agency", user, value, onSelect: setValue, disabled: false }); }
  await React.act(async () => root.render(React.createElement(Harness)));
}
async function unmount() { await React.act(async () => root.unmount()); container.remove(); }
function input(label) { return [...container.querySelectorAll("label")].find((node) => node.textContent.startsWith(label))?.querySelector("input"); }
async function type(label, value) { const node = input(label); assert.ok(node, label); await React.act(async () => { Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set.call(node, value); node.dispatchEvent(new window.Event("input", { bubbles: true })); }); }
function button(label) { return [...container.querySelectorAll("button")].find((node) => node.textContent.includes(label)); }
async function click(label) { const node = button(label); assert.ok(node, label); await React.act(async () => node.click()); }

for (const search of ["SUB-1", "TERM-1"]) test(`rendered search ${search} resolves selected number`, async () => {
  handler = async () => ({ count: 1, results: [result] });
  await mount(); await type("Search Sub-Agent", search); assert.equal(requests.length, 0); await wait();
  assert.ok(requests[0].path.startsWith("agencies/7/payment-numbers/?search="));
  assert.ok(!container.textContent.includes("Selected:")); await click("Existing payer");
  assert.ok(container.textContent.includes("Selected: Existing payer · Sub-Agent Number SUB-1 · Terminal TERM-1"));
  assert.equal(button("Existing payer").getAttribute("aria-pressed"), "true"); await unmount();
});

test("payer search renders multiple numbers and disables inactive results", async () => {
  handler = async () => ({ count: 3, results: [result, { ...result, id: 2, sub_agent_number: "SUB-2" }, { ...result, id: 3, sub_agent_number: "SUB-3", selectable: false, is_active: false }] });
  await mount(); await type("Search Sub-Agent", "Existing"); await wait();
  assert.equal(container.querySelectorAll(".payment-number-results button").length, 3);
  assert.equal(button("SUB-3").disabled, true); await click("SUB-2");
  assert.ok(container.textContent.includes("Selected: Existing payer · Sub-Agent Number SUB-2")); await unmount();
});

test("quick-create preserves duplicate errors, blocks double submission, selects new number and focuses success", async () => {
  let failure = true, resolveCreate;
  handler = async (path, options) => {
    if (options?.method === "POST") {
      if (failure) throw { status: 400, payload: { terminal_number: ["Terminal Number TERM-1 already exists and is assigned to Sub-Agent Number SUB-1 for Existing payer."] } };
      return new Promise((resolve) => { resolveCreate = resolve; });
    }
    return path.startsWith("payment-payers/") ? { count: 1, results: [{ id: 9, payer_name: "Existing payer" }] } : { count: 0, results: [] };
  };
  await mount(); await type("Search Sub-Agent", "UNKNOWN"); await wait();
  assert.ok(container.textContent.includes("Sub-Agent or Terminal Number not found in this agency."));
  await click("Add Sub-Agent and Terminal Number"); await type("Search existing payer", "Existing"); await wait();
  assert.ok(requests.some((request) => request.path.includes("payment-payers/?agency=7&active=true&search=Existing")));
  await click("Existing payer"); assert.equal(container.querySelector("a")?.getAttribute("href"), "/dashboard/payments/payers?create=1&agency=7");
  await type("New Sub-Agent", "SUB-NEW"); await type("New Terminal", "TERM-1");
  await React.act(async () => container.querySelector('input[type="checkbox"]').click()); await click("Add numbers");
  assert.ok(container.querySelector('[role="alert"]').textContent.includes("already exists"));
  assert.equal(input("New Sub-Agent").value, "SUB-NEW"); assert.equal(input("New Terminal").value, "TERM-1");
  failure = false; await click("Add numbers");
  const before = requests.filter((request) => request.options?.method === "POST").length;
  await click("Adding…"); assert.equal(requests.filter((request) => request.options?.method === "POST").length, before);
  await React.act(async () => resolveCreate(result)); assert.equal(container.querySelector("fieldset"), null);
  assert.equal(document.activeElement.textContent, "Sub-Agent and Terminal Number added successfully.");
  assert.ok(container.textContent.includes("Selected: Existing payer")); await unmount();
});

test("read-only accountant cannot search or quick-create", async () => {
  handler = async () => { throw new Error("Must not request"); };
  await mount({ role: "ACCOUNTANT", agency_assignments: [{ agency: { id: 7 }, can_edit: false }] });
  assert.equal(input("Search Sub-Agent").disabled, true); await wait(); assert.equal(requests.length, 0);
  assert.equal(button("Add Sub-Agent and Terminal Number"), undefined); await unmount();
});
