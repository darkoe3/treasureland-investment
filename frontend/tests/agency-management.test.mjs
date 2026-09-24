import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as operations from "../lib/agency-operations.js";
import * as api from "../lib/client-api.js";
import { isAllowedBackendProxyPath as allowed } from "../lib/controlled-proxy-path.js";
const require = createRequire(import.meta.url);
const { transformSync } = require("next/dist/build/swc");
const source = await readFile(new URL("../components/AgenciesClient.js", import.meta.url), "utf8");
const compiled = transformSync(source, { filename: "AgenciesClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
const agency = { id: 1, name: "Musa", code: "MUSA", is_active: true, counts: { editable_daily_sheets: 1 } };
const inactive = { ...agency, id: 2, name: "Inactive agency", code: "OTHER", is_active: false };
const draft = { name: "Musa", code: "MUSA", reason: "", confirmed: false, acknowledge_editable_sheets: false, confirm_code_change: false };
export function harness({ role = "SUPER_ADMIN", editor = null, fields = {}, request = async () => agency } = {}) {
  const states = [[agency, inactive], false, "", "", "", "", editor, { ...draft }, fields, false, null];
  let index = 0;
  const hooks = { ...React, useEffect() {}, useRef() { return { current: { close() {} } }; }, useState(initial) { const n = index++; if (!(n in states)) states[n] = initial; return [states[n], (value) => { states[n] = typeof value === "function" ? value(states[n]) : value; }]; } };
  const compiledModule = { exports: {} };
  vm.runInNewContext(compiled, { module: compiledModule, exports: compiledModule.exports, Date, require(name) {
    if (name === "react") return hooks;
    if (name === "react/jsx-runtime") return require(name);
    if (name === "next/link") return function TestLink({ href, children }) { return React.createElement("a", { href }, children); };
    if (name === "../lib/client-api") return { ...api, clientRequest: request };
    if (name === "../lib/agency-operations") return operations;
    throw new Error(name);
  } });
  const render = () => { index = 0; return compiledModule.exports.default({ user: { role } }); };
  return { states, render, html: () => renderToStaticMarkup(render()) };
}
function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props?.children)) { const result = find(child, predicate); if (result) return result; }
  return null;
}
test("agency mutation controls are exclusive to Super Admin", () => {
  const admin = harness().html();
  for (const label of ["Add Agency", "Edit", "Deactivate", "Reactivate"]) assert.ok(admin.includes(label));
  const accountant = harness({ role: "ACCOUNTANT" }).html();
  for (const label of ["Add Agency", "Edit", "Deactivate", "Reactivate", "<dialog"]) assert.ok(!accountant.includes(label));
  assert.match(accountant, /View details/);
});
test("search and status filters change the rendered agency list", () => {
  const ui = harness();
  find(ui.render(), (n) => n.type === "input" && n.props.type === "search").props.onChange({ target: { value: " other " } });
  assert.doesNotMatch(ui.html(), /<h2>Musa/);
  assert.match(ui.html(), /Inactive agency/);
  find(ui.render(), (n) => n.type === "select").props.onChange({ target: { value: "true" } });
  assert.match(ui.html(), /No agencies match/);
});
test("deactivation requires reason, confirmation and editable-sheet acknowledgement", () => {
  const ui = harness({ editor: { mode: "deactivate", row: agency, impact: agency.counts } });
  const submit = () => find(ui.render(), (n) => n.type === "button" && n.props.type === "submit");
  assert.equal(submit().props.disabled, true);
  ui.states[7] = { ...draft, reason: "Closing", confirmed: true };
  assert.equal(submit().props.disabled, true);
  assert.match(ui.html(), /Draft, Returned or Reopened/);
  assert.match(ui.html(), /Assigned accountants/);
  ui.states[7].acknowledge_editable_sheets = true;
  assert.equal(submit().props.disabled, false);
});
test("reactivation requires explicit confirmation and reason", () => {
  const ui = harness({ editor: { mode: "reactivate", row: inactive } });
  ui.states[7] = { ...draft, reason: "Resume operations" };
  assert.equal(find(ui.render(), (n) => n.props.type === "submit").props.disabled, true);
  ui.states[7].confirmed = true;
  assert.equal(find(ui.render(), (n) => n.props.type === "submit").props.disabled, false);
});
test("backend field validation remains beside the relevant input", async () => {
  const ui = harness({ editor: { mode: "edit", row: agency }, request: async () => { throw new api.ClientApiError("Duplicate", 400, { code: ["Agency code MUSA already exists. Edit the existing agency instead."] }); } });
  await find(ui.render(), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.match(ui.html(), /Agency code MUSA already exists/);
});
test("code edits require confirmation and PATCH preserves the selected ID", async () => {
  let call;
  const ui = harness({ editor: { mode: "edit", row: agency }, request: async (...args) => { call = args; return agency; } });
  ui.states[7].code = "NEW";
  assert.equal(find(ui.render(), (n) => n.props.type === "submit").props.disabled, true);
  ui.states[7].confirm_code_change = true;
  await find(ui.render(), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(call[0], "/api/backend/agencies/1/");
  assert.equal(call[1].method, "PATCH");
  assert.equal(JSON.parse(call[1].body).confirm_code_change, true);
});
test("controlled proxy allows only exact agency paths and methods", () => {
  for (const [path, methods] of [["agencies", ["GET", "POST"]], ["agencies/12", ["GET", "PATCH"]], ["agencies/12/impact", ["GET"]], ["agencies/12/deactivate", ["POST"]], ["agencies/12/reactivate", ["POST"]]]) {
    for (const method of ["GET", "POST", "PATCH", "PUT", "DELETE"]) assert.equal(allowed(path, method), methods.includes(method), `${method} ${path}`);
  }
  for (const path of ["agencies/12/delete", "agencies/12/deactivate/extra", "agencies/me", "agencies/../accountants", "agencies/12/activate"]) assert.equal(allowed(path, "POST"), false);
});
