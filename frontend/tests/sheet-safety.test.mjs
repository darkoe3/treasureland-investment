import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as clientApi from "../lib/client-api.js";
import * as shared from "../lib/phase4-operations.js";
import * as safety from "../lib/sheet-controls.js";
import { isAllowedBackendProxyPath } from "../lib/controlled-proxy-path.js";
import { controlledBackendProxyResponse } from "../lib/backend-proxy.js";
const require = createRequire(import.meta.url);
const source = await readFile(new URL("../components/SheetSafetyControls.js", import.meta.url), "utf8");
const { transformSync } = require("next/dist/build/swc");
const compiled = transformSync(source, { filename: "SheetSafetyControls.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
const admin = { role: "SUPER_ADMIN" };
const sheet = { id: 1, agency_name: "Agency", transaction_date: "2026-08-27", status: "DRAFT", transaction_count: 3, gross_sales: "100.00", total_to_pay: "95.00", can_reset: true, can_delete: false };
function harness({ user = admin, target = sheet, request = async () => ({}), onReset = async () => {} } = {}) {
  const states = ["reset", "", false, false, { error: "", success: "" }];
  const refs = [{ current: { showModal() {}, close() {} } }, { current: false }];
  let si = 0, ri = 0;
  const fakeReact = { ...React, useState(initial) { const i = si++; if (!(i in states)) states[i] = initial; return [states[i], (v) => { states[i] = v; }]; }, useRef() { return refs[ri++]; } };
  const compiledModule = { exports: {} };
  vm.runInNewContext(compiled, { module: compiledModule, exports: compiledModule.exports, require(name) {
    if (name === "react") return fakeReact;
    if (name === "react/jsx-runtime") return require(name);
    if (name === "next/navigation") return { useRouter: () => ({ push() {} }) };
    if (name === "../lib/client-api") return { ...clientApi, clientRequest: request };
    if (name === "../lib/phase4-operations") return shared;
    if (name === "../lib/sheet-controls") return safety;
    throw new Error(name);
  } });
  const render = () => { si = 0; ri = 0; return compiledModule.exports.default({ user, sheet: target, onReset }); };
  return { states, render, html: () => renderToStaticMarkup(render()) };
}
function nodes(node) { return React.isValidElement(node) ? [node, ...React.Children.toArray(node.props.children).flatMap(nodes)] : []; }
function find(h, predicate) { const node = nodes(h.render()).find(predicate); assert.ok(node); return node; }
const event = { preventDefault() {} };
test("Reset only appears for eligible Super Admin sheets; workflow guidance and Delete eligibility", () => {
  for (const status of ["DRAFT", "RETURNED", "REOPENED"]) assert.equal(safety.sheetControls(admin, { ...sheet, status }).reset, true);
  assert.equal(harness({ user: { role: "ACCOUNTANT" } }).html(), "");
  for (const status of ["SUBMITTED", "APPROVED"]) {
    const controls = safety.sheetControls(admin, { ...sheet, status });
    assert.equal(controls.reset, false); assert.ok(controls.guidance);
  }
  assert.equal(safety.sheetControls(admin, { ...sheet, is_archived: true }).reset, false);
  assert.equal(safety.sheetControls(admin, sheet).delete, false);
  assert.equal(safety.sheetControls(admin, { ...sheet, can_delete: true }).delete, true);
  assert.ok(harness({ target: { ...sheet, can_delete: true } }).html().includes("Delete sheet"));
});
test("reason, checkbox and loading gate confirmation; duplicate requests suppressed and totals refreshed", async () => {
  let finish, calls = 0, updated;
  const zero = { ...sheet, transaction_count: 0, gross_sales: "0.00", total_to_pay: "0.00" };
  const h = harness({ request: async (path, options) => { calls++; assert.equal(path, "/api/backend/daily-sheets/1/reset/"); assert.equal(JSON.parse(options.body).confirm_reset, true); await new Promise((r) => { finish = r; }); return zero; }, onReset: async (value) => { updated = value; } });
  const submitButton = () => find(h, (n) => n.type === "button" && n.props.type === "submit");
  assert.equal(submitButton().props.disabled, true);
  h.states[1] = "Reason"; assert.equal(submitButton().props.disabled, true);
  h.states[2] = true; assert.equal(submitButton().props.disabled, false);
  const handler = find(h, (n) => n.type === "form").props.onSubmit;
  const pending = handler(event); await handler(event);
  assert.equal(calls, 1); assert.equal(submitButton().props.disabled, true);
  finish(); await pending;
  assert.equal(updated.gross_sales, "0.00"); assert.ok(h.html().includes("Sheet reset."));
});
test("backend validation is readable in the actual dialog", async () => {
  const detail = "Archived sheets cannot be reset.";
  const h = harness({ request: async () => { throw new clientApi.ClientApiError(detail, 400, { detail }); } });
  h.states[1] = "Reason"; h.states[2] = true;
  await find(h, (n) => n.type === "form").props.onSubmit(event);
  assert.ok(h.html().includes(detail)); assert.equal(h.states[3], false);
});
test("permanent deletion uses explicit confirmation and correct method", async () => {
  let options;
  const h = harness({ target: { ...sheet, can_delete: true }, request: async (path, value) => { assert.equal(path, "/api/backend/daily-sheets/1/"); options = value; } });
  h.states[0] = "delete"; h.states[1] = "Unused"; h.states[2] = true;
  assert.ok(h.html().includes("Deletion is permanent"));
  await find(h, (n) => n.type === "form").props.onSubmit(event);
  assert.equal(options.method, "DELETE"); assert.equal(JSON.parse(options.body).confirm_permanent_delete, true);
});
test("exact reset/delete allowlist and CSRF enforcement preserve upstream bodies", async () => {
  assert.equal(isAllowedBackendProxyPath("daily-sheets/12/reset/", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/12/", "DELETE"), true);
  for (const path of ["daily-sheets/reset", "daily-sheets/all/reset", "daily-sheets/12/reset/extra", "daily-sheets/12/reset-all"]) assert.equal(isAllowedBackendProxyPath(path, "POST"), false);
  for (const method of ["GET", "PATCH", "DELETE"]) assert.equal(isAllowedBackendProxyPath("daily-sheets/12/reset", method), false);
  for (const [method, path] of [["POST", ["daily-sheets", "12", "reset"]], ["DELETE", ["daily-sheets", "12"]]]) {
    let calls = 0;
    const deps = { cookieStore: {}, validateCsrf: () => false, backendRequest: async () => { calls++; return { status: 400, payload: { detail: "Safe validation" } }; }, onDiagnostics() {} };
    const request = () => new Request("http://localhost/api/backend/" + path.join("/"), { method, body: "{}" });
    assert.equal((await controlledBackendProxyResponse(request(), { params: { path } }, deps)).status, 403);
    assert.equal(calls, 0);
    deps.validateCsrf = () => true;
    const result = await controlledBackendProxyResponse(request(), { params: { path } }, deps);
    assert.equal(result.status, 400); assert.equal((await result.json()).detail, "Safe validation");
  }
});
test("dialog has viewport bounds and wrapping to contain long content", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(css, /width: min\(36rem, calc\(100vw - 2rem\)\)/);
  assert.match(css, /max-height: calc\(100dvh - 2rem\)/);
  assert.match(css, /overflow-wrap: anywhere/);
});
