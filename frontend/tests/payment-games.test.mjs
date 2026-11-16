import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import vm from "node:vm";
import { JSDOM } from "jsdom";
import * as gameOperations from "../lib/payment-games.js";
import { isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "../lib/controlled-proxy-path.js";
const dom = new JSDOM("<!doctype html><body></body>", { url: "http://localhost" });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import("react");
const { createRoot } = await import("react-dom/client");
const require = createRequire(import.meta.url);
const source = await readFile(new URL("../components/PaymentGamePicker.js", import.meta.url), "utf8");
const compiled = require("next/dist/build/swc").transformSync(source, { filename: "PaymentGamePicker.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
let handler, requests;
const mod = { exports: {} };
vm.runInNewContext(compiled, { exports: mod.exports, module: mod, encodeURIComponent, require(name) {
  if (name.includes("client-api")) return { apiPath: (path) => path, clientRequest: async (path) => { requests.push(path); return handler(path); } };
  if (name.includes("payment-games")) return gameOperations;
  return require(name);
} });
const games = [
 { game_id: 1, name: "Timed game", category: "TIMED", business_date: "2026-11-09", is_whole_day: false, closing_time: "12:30", draw_time: "12:45" },
 { game_id: 2, name: "Ghana replacement", category: "GHANA", business_date: "2026-11-09", is_whole_day: true, holiday_override_applied: true, holiday_name: "Holiday" },
 { game_id: 3, name: "Double Chance", category: "DOUBLE_CHANCE", business_date: "2026-11-09", is_whole_day: true },
];
async function mount(t, props = {}) {
  requests = [];
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  function Harness() {
    const [value, onChange] = React.useState("");
    return React.createElement(mod.exports.default, { agency: 7, businessDate: "2026-11-09", value, onChange, ...props });
  }
  await React.act(async () => root.render(React.createElement(Harness)));
  t.after(async () => { await React.act(async () => root.unmount()); container.remove(); });
  return container;
}
test("effective-game selector loads agency/date, labels categories and holidays, requires explicit selection", async (t) => {
  handler = async () => games;
  const container = await mount(t);
  assert.deepEqual(requests, ["agencies/7/payment-effective-games/?business_date=2026-11-09"]);
  const select = container.querySelector("select");
  assert.equal(select.value, ""); assert.equal(select.required, true);
  for (const label of ["Timed", "Ghana (Whole Day)", "Double Chance", "Whole Day", "Closing 12:30 / Draw 12:45", "Holiday Override"]) assert.ok(container.textContent.includes(label));
  await React.act(async () => { select.value = "2"; select.dispatchEvent(new window.Event("change", { bubbles: true })); });
  assert.match(container.textContent, /Review selected game: Ghana replacement/);
  select.focus(); assert.equal(document.activeElement, select);
});
test("loading and empty states prevent choosing a game", async (t) => {
  let resolve;
  handler = () => new Promise((done) => { resolve = done; });
  const container = await mount(t);
  assert.match(container.textContent, /Loading effective games/);
  assert.equal(container.querySelector("select").disabled, true);
  await React.act(async () => resolve([]));
  assert.match(container.textContent, /No effective games/);
  assert.equal(container.querySelector("select").disabled, true);
});
test("failed loading is recoverable without selecting a game", async (t) => {
  handler = async () => { throw Object.assign(new Error("The schedule is unavailable for this date."), { status: 400 }); };
  const container = await mount(t);
  assert.match(container.textContent, /The schedule is unavailable for this date/);
  handler = async () => games;
  await React.act(async () => container.querySelector("button").click());
  assert.equal(container.querySelector("select").disabled, false);
  assert.equal(container.querySelector("select").value, "");
});
test("date is required before any schedule request", async (t) => {
  handler = async () => games;
  const container = await mount(t, { businessDate: "" });
  assert.equal(requests.length, 0); assert.match(container.textContent, /Select an agency and business date/);
});
test("legacy and stored holiday receipt labels need no live schedule", () => {
  assert.equal(gameOperations.gameLabel(null), "Game: Not assigned - legacy obligation.");
  assert.match(gameOperations.gameLabel(games[1]), /2026-11-09.*Whole Day.*Holiday Game: Holiday/);
});
test("controlled proxy permits only exact effective-game GET endpoint", () => {
  assert.equal(isAllowedBackendProxyPath("agencies/7/payment-effective-games/?business_date=2026-11-09", "GET"), true);
  assert.equal(isBinaryBackendProxyPath("agencies/7/payment-effective-games/", "GET"), false);
  for (const method of ["POST", "PATCH", "DELETE", "PUT"]) assert.equal(isAllowedBackendProxyPath("agencies/7/payment-effective-games/", method), false);
  for (const path of ["agencies/all/payment-effective-games", "agencies/7/payment-effective-games/1", "payment-effective-games", "agencies/7/other"]) assert.equal(isAllowedBackendProxyPath(path, "GET"), false);
});
test("controlled proxy permits deletion only for a payment-obligation detail", () => {
  assert.equal(isAllowedBackendProxyPath("payment-obligations/12/", "DELETE"), true);
  assert.equal(isAllowedBackendProxyPath("payment-obligations/", "DELETE"), false);
  assert.equal(isAllowedBackendProxyPath("payment-payers/12/", "DELETE"), false);
});


test("new obligation preserves values after duplicate failure, requires number/date/game, and blocks double submit", async (t) => {
  const operations = await import("../lib/payment-operations.js");
  const text = await readFile(new URL("../components/PaymentsClient.js", import.meta.url), "utf8");
  const code = require("next/dist/build/swc").transformSync(text + "\nexport { Obligations };", { filename: "PaymentsClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; };
  let posts = [], fail = true, finish;
  const obligationModule = { exports: {} };
  vm.runInNewContext(code, { module: obligationModule, exports: obligationModule.exports, window, URLSearchParams, setTimeout, clearTimeout, require(name) {
    if (name === "next/link") return function TestLink({ children, ...props }) { return React.createElement("a", props, children); };
    if (name.includes("PaymentGamePicker")) return mod.exports.default;
    if (name.includes("PaymentNumberPicker")) return function NumberStub({ onSelect, value }) { return React.createElement(React.Fragment, null,
      React.createElement("button", { type: "button", onClick: () => onSelect({ id: 8, agency: 7, payer: 9, sub_agent_number: "SUB-8", terminal_number: "TERM-8" }) }, "Choose SUB-8 / TERM-8"),
      value ? React.createElement("p", null, `Selected ${value.sub_agent_number} / ${value.terminal_number}`) : null); };
    if (name.includes("PaymentNumberLedger")) return { usePaymentPage: () => ({ rows: [], setPage() {} }), PageControls: () => null };
    if (name.includes("payment-games")) return gameOperations;
    if (name.includes("payment-operations")) return operations;
    if (name.includes("client-api")) return { apiPath: (path) => path, clientRequest: async (path, options) => {
      if (!options || options.method === "GET") return games;
      posts.push(JSON.parse(options.body));
      if (fail) throw { status: 400, payload: { game: "An obligation already exists. Open the existing obligation to record payment." } };
      return new Promise((resolve) => { finish = resolve; });
    } };
    return require(name);
  } });
  handler = async () => games;
  requests = [];
  const container = document.createElement("div"); document.body.append(container);
  let root = createRoot(container);
  const props = { user: { role: "SUPER_ADMIN" }, data: { agencies: [{ id: 7, name: "Agency" }], payers: [{ id: 9, agency: 7, payer_name: "Payer" }], obligations: [] }, onRefresh: async () => {} };
  t.after(async () => { await React.act(async () => root.unmount()); container.remove(); });
  await React.act(async () => root.render(React.createElement(obligationModule.exports.Obligations, props)));
  const button = (label) => [...container.querySelectorAll("button")].find((node) => node.textContent === label);
  await React.act(async () => button("Create obligation").click());
  await React.act(async () => button("Choose SUB-8 / TERM-8").click());
  const field = (label) => [...container.querySelectorAll("dialog label")].find((node) => node.textContent.startsWith(label))?.querySelector("input,select");
  async function set(label, value) {
    const node = field(label);
    await React.act(async () => { Object.getOwnPropertyDescriptor(node.tagName === "SELECT" ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype, "value").set.call(node, value); node.dispatchEvent(new window.Event(node.tagName === "SELECT" ? "change" : "input", { bubbles: true })); });
  }
  await set("Business date", "2026-11-09");
  assert.equal(field("Game").value, "");
  assert.equal(container.querySelector("dialog button[type=submit]").disabled, true);
  await set("Game", "2"); await set("Description", "Collection"); await set("Total expected", "100");
  const submit = () => container.querySelector("dialog form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await React.act(async () => submit());
  assert.match(container.querySelector("dialog").textContent, /Open the existing obligation/);
  assert.equal(field("Description").value, "Collection"); assert.equal(field("Game").value, "2");
  fail = false;
  await React.act(async () => { submit(); submit(); });
  assert.equal(posts.length, 2);
  assert.equal(posts[0].creation_key, posts[1].creation_key);
  assert.equal(posts[1].business_date, "2026-11-09"); assert.equal(posts[1].sub_agent_number, 8);
  assert.equal(container.querySelector("dialog button[type=submit]").disabled, true);
  await React.act(async () => finish({ id: 20, ...posts[1], game_snapshot: games[1] }));
  assert.equal(container.querySelector("dialog"), null);

  await React.act(async () => root.unmount());
  const replacementParams = new URLSearchParams({
    create: "1",
    agency: "7",
    payer: "9",
    sub_agent_number: "8",
    sub_agent_number_label: "SUB-8",
    terminal_number: "TERM-8",
    business_date: "2026-11-09",
    game: "2",
  });
  window.history.replaceState({}, "", `/?${replacementParams}`);
  root = createRoot(container);
  await React.act(async () => root.render(React.createElement(obligationModule.exports.Obligations, props)));
  assert.equal(field("Agency").value, "7");
  assert.equal(field("Business date").value, "2026-11-09");
  assert.equal(field("Game").value, "2");
  assert.match(container.textContent, /Selected SUB-8 \/ TERM-8/);
  await set("Description", "Replacement");
  await set("Total expected", "100");
  fail = true;
  await React.act(async () => submit());
  assert.equal(posts[2].agency, "7");
  assert.equal(posts[2].payer, "9");
  assert.equal(posts[2].sub_agent_number, "8");
  assert.equal(posts[2].business_date, "2026-11-09");
  assert.equal(posts[2].game, "2");
});
