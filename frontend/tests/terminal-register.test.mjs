import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as operations from "../lib/terminal-operations.js";
import * as api from "../lib/client-api.js";
import { isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "../lib/controlled-proxy-path.js";
import { controlledBackendProxyResponse } from "../lib/backend-proxy.js";

const require = createRequire(import.meta.url);
const { transformSync } = require("next/dist/build/swc");
const source = await readFile(new URL("../components/TerminalNumbersClient.js", import.meta.url), "utf8");
const compiled = transformSync(source, { filename: "TerminalNumbersClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
const agencies = [{ id: 1, name: "Musa" }, { id: 2, name: "Sango" }];
const people = [{ id: 1, agency: 1, full_name: "Ayo", is_active: true, tpm_codes: [{ id: 10, code: "0001", is_active: true }] }, { id: 2, agency: 2, full_name: "Bisi", is_active: true, tpm_codes: [{ id: 20, code: "0002", is_active: true }] }];
const terminal = { id: 1, agency: 1, agency_name: "Musa", person: 1, person_name: "Ayo", sub_agent_number: 10, sub_agent_number_value: "0001", terminal_number: "00009", is_active: true, updated_at: "2026-09-16" };
const batch = { id: 1, agency: 1, status: "PREVIEWED", original_filename: "test.xlsx", expires_at: "2099-01-01", warnings: [], errors: [], preview_payload: { rows: [{ row: 2, terminal_number: "00009", sub_agent_number_value: "0001", name: "Ayo", classification: "New" }] } };
const draft = { agency: "1", person: "1", sub_agent_number: "10", terminal_number: "00009", is_active: true, confirmed: false, reason: "" };

test("sub-agent register selector posts fixed type and renders names without terminals", async () => {
  const preview = { ...batch, preview_payload: { register_type: "SUB_AGENT", mode: "LINK_EXISTING",
    creation_counts: { people: 0, sub_agent_numbers: 0, terminals: 0 },
    rows: [{ row: 9, classification: "UNCHANGED", name: "Ayo", supplied_values: ["0001", "Ayo"] }] } };
  const calls = [];
  const ui = harness({ uploadPage: true, request: async (path, options) => { calls.push([path, options]); return preview; } });
  assert.match(ui.html(), /Sub-Agent Register — no terminal numbers/);
  find(ui.render(), (n) => n.type === "select" && n.props.value === "TERMINAL").props.onChange({ target: { value: "SUB_AGENT" } });
  await find(ui.render(), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls[0][1].body.get("register_type"), "SUB_AGENT");
  assert.match(ui.html(), /Row 9<\/td><td>0001<\/td><td>Not assigned<\/td><td>Ayo/);
  assert.match(ui.html(), /New Terminal Numbers: 0/);
  assert.equal(operations.canConfirmTerminalImport(preview, true, Date.now(), ""), false);
  assert.equal(operations.canConfirmTerminalImport(preview, true, Date.now(), "Verified"), true);
});

test("unassigned listing opens manual terminal assignment with selected owner", () => {
  const ui = harness();
  assert.match(ui.html(), /Terminal Number: Not assigned/);
  find(ui.render(), (n) => n.type === "button" && n.props.children === "Assign Terminal").props.onClick();
  assert.equal(ui.states[4].sub_agent_number, "20");
  assert.equal(ui.states[4].person, "2");
  assert.equal(ui.states[4].agency, "2");
  assert.doesNotMatch(harness({ user: { role: "ACCOUNTANT" } }).html(), /Assign Terminal/);
});

test("grouped messages recover Excel row numbers from placeholder rows", () => {
  const groups = operations.groupImportMessages([{ row: "-", cell: "B27", field: "SUB AGT NOS", message: "-" }]);
  assert.equal(groups[0].rows[0].message, "Row 27: SUB AGT NOS is numeric and may have lost leading zeroes.");
});

function harness({ user = { role: "SUPER_ADMIN" }, editor = null, values = draft, preview = null, request = async () => [], uploadPage = false } = {}) {
  const states = [[terminal], people, { agency: "", active: "", search: "" }, editor, values, null, "1", new Blob(["xlsx"]), preview, false, false, "", ""];
  let index = 0;
  const hooks = { ...React, useEffect() {}, useState(initial) { const n = index++; if (!(n in states)) states[n] = typeof initial === "function" ? initial() : initial; return [states[n], (value) => { states[n] = typeof value === "function" ? value(states[n]) : value; }]; } };
  const compiledModule = { exports: {} };
  vm.runInNewContext(compiled, { module: compiledModule, exports: compiledModule.exports, FormData, Date, window: { confirm: () => true }, require(name) {
    if (name === "react") return hooks;
    if (name === "react/jsx-runtime") return require(name);
    if (name === "next/link") return function TestLink({ href, children }) { return React.createElement("a", { href }, children); };
    if (name === "../lib/client-api") return { ...api, clientRequest: request };
    if (name === "../lib/terminal-operations") return operations;
    throw new Error(name);
  } });
  const render = () => { index = 0; return compiledModule.exports.default({ user, agencies, uploadPage }); };
  return { states, render, html: () => renderToStaticMarkup(render()) };
}
function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props?.children)) { const result = find(child, predicate); if (result) return result; }
  return null;
}

test("terminal navigation and actual role-based buttons", async () => {
  const shell = await readFile(new URL("../components/DashboardShell.js", import.meta.url), "utf8");
  assert.equal((shell.match(/label: "Terminal Numbers"/g) || []).length, 2);
  const admin = harness().html(); const accountant = harness({ user: { role: "ACCOUNTANT" } }).html();
  for (const label of ["Add terminal", "Upload Excel", "Reassign", "Deactivate", "View history"]) { assert.ok(admin.includes(label)); assert.ok(!accountant.includes(label)); }
  assert.ok(accountant.includes("00009"));
});

test("manual form filters dependencies and resets stale choices", () => {
  const ui = harness({ editor: { mode: "add" } });
  const selects = [];
  function collect(node) { if (!node || typeof node !== "object") return; if (node.type === "select") selects.push(node); React.Children.forEach(node.props?.children, collect); }
  collect(ui.render());
  assert.equal(operations.terminalChoices(people, 1, 2).codes.length, 0);
  assert.deepEqual(operations.terminalChoices(people, 1, 1).people.map((p) => p.full_name), ["Ayo"]);
  selects[0].props.onChange({ target: { value: "2" } });
  assert.equal(ui.states[4].person, ""); assert.equal(ui.states[4].sub_agent_number, "");
  assert.deepEqual(operations.terminalPayload(draft, "add"), { agency: 1, person: 1, sub_agent_number: 10, terminal_number: "00009", is_active: true });
});

test("edit submits only terminal text; reassignment requires reason and explicit checkbox", async () => {
  assert.deepEqual(operations.terminalPayload(draft, "edit"), { terminal_number: "00009" });
  assert.throws(() => operations.terminalPayload(draft, "reassign"), /reason/);
  const calls = [];
  const ui = harness({ editor: { mode: "reassign", item: terminal }, values: { ...draft, agency: "2", person: "2", sub_agent_number: "20", reason: "Replacement", confirmed: true }, request: async (path, options) => { calls.push([path, options]); return []; } });
  assert.match(ui.html(), /From Musa/); assert.match(ui.html(), /To Sango/);
  await find(ui.render(), (node) => node.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls[0][0], "/api/backend/terminal-numbers/1/reassign/");
  assert.equal(JSON.parse(calls[0][1].body).confirmed, true);
});

test("upload uses multipart preview and row errors are readable; confirm is gated", async () => {
  const calls = [];
  const ui = harness({ uploadPage: true, request: async (path, options) => { calls.push([path, options]); return batch; } });
  await find(ui.render(), (node) => node.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls[0][0], "/api/backend/terminal-number-imports/preview/");
  assert.equal(calls[0][1].body.get("agency"), "1");
  assert.ok(ui.html().includes("Import preview"));
  ui.states[8] = { ...batch, errors: [{ row: 2, message: "Row 2: NAME does not match the database person." }] };
  assert.ok(ui.html().includes("Row 2: NAME does not match"));
  assert.equal(operations.canConfirmTerminalImport(ui.states[8], true), false);
  assert.equal(operations.canConfirmTerminalImport(batch, false), false);
  assert.equal(operations.canConfirmTerminalImport(batch, true), true);
  assert.equal(operations.canConfirmTerminalImport({ ...batch, expires_at: "2000-01-01" }, true), false);
});

test("exact terminal proxy methods reject arbitrary destinations and unsupported actions", () => {
  for (const [path, methods] of [["terminal-numbers", ["GET", "POST"]], ["terminal-numbers/1", ["GET", "PATCH"]], ["terminal-numbers/1/history", ["GET"]], ["terminal-number-imports/template", ["GET"]], ["terminal-number-imports/preview", ["POST"]], ["terminal-number-imports/1", ["GET"]], ...["confirm", "cancel"].map((a) => [`terminal-number-imports/1/${a}`, ["POST"]]), ...["reassign", "deactivate", "reactivate"].map((a) => [`terminal-numbers/1/${a}`, ["POST"]])]) {
    for (const method of ["GET", "POST", "PATCH", "DELETE", "PUT"]) assert.equal(isAllowedBackendProxyPath(path, method), methods.includes(method), `${method} ${path}`);
  }
  for (const path of ["terminal-numbers/1/delete", "terminal-numbers/1/history/extra", "terminal-number-imports", "https://evil.test", "terminal-numbers/../accountants"]) assert.equal(isAllowedBackendProxyPath(path, "POST"), false);
  assert.equal(isBinaryBackendProxyPath("terminal-number-imports/template", "GET"), true);
});

test("terminal proxy preserves multipart bytes, backend status/body and enforces CSRF", async () => {
  const body = new FormData(); body.set("agency", "1"); body.set("file", new Blob([new Uint8Array([80, 75, 0, 255])]), "register.xlsx");
  const request = new Request("http://localhost/api/backend/terminal-number-imports/preview", { method: "POST", body });
  const original = new Uint8Array(await request.clone().arrayBuffer());
  let calls = 0;
  const deps = { validateCsrf: () => true, cookieStore: {}, onDiagnostics() {}, backendRequest: async (path, options) => {
    calls++; assert.equal(path, "/terminal-number-imports/preview"); assert.deepEqual(new Uint8Array(options.body), original);
    assert.equal(options.headers["Content-Type"], request.headers.get("content-type"));
    return { status: 422, payload: { detail: "Row 2: Unknown Sub-Agent Number." } };
  } };
  const context = { params: { path: ["terminal-number-imports", "preview"] } };
  const denied = await controlledBackendProxyResponse(request.clone(), context, { ...deps, validateCsrf: () => false });
  assert.equal(denied.status, 403); assert.equal(calls, 0);
  const response = await controlledBackendProxyResponse(request, context, deps);
  assert.equal(response.status, 422); assert.deepEqual(await response.json(), { detail: "Row 2: Unknown Sub-Agent Number." });
});

test("responsive layout bounds grids and preview overflow at the component boundary", async () => {
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(css, /\.terminal-register\s*\{[^}]*min-width: 0;[^}]*max-width: 100%/);
  assert.match(css, /minmax\(min\(100%, 240px\), 1fr\)/);
  assert.match(css, /\.terminal-table\s*\{[^}]*overflow-x: auto/);
  assert.match(harness().html(), /terminal-cards/);
});

test("large import errors and numeric warnings group compactly with expandable rows", () => {
  const errors = Array.from({ length: 199 }, (_, index) => ({ row: index + 2, category: "INVALID", detail: "Missing required values", message: `Row ${index + 2}: Missing required values` }));
  const groups = operations.groupImportMessages(errors);
  assert.equal(groups.length, 1); assert.equal(groups[0].rows.length, 199);
  const ui = harness({ uploadPage: true, preview: { ...batch, errors } });
  const html = ui.html();
  assert.equal((html.match(/<details/g) || []).length, 1);
  assert.match(html, /199 rows/); assert.match(html, /Row 200/);
  assert.match(html, /Preview filter/);
  const warnings = [{ field: "SUB AGT NOS", message: "sub" }, { field: "TERMINAL NOS", message: "terminal" }];
  assert.equal(operations.groupImportMessages(warnings).length, 2);
});

test("onboarding defaults safely and confirmation requires reason and numeric acknowledgement", async () => {
  const calls = [];
  const ui = harness({ uploadPage: true, request: async (path, options) => { calls.push(options); return batch; } });
  await find(ui.render(), (node) => node.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls[0].body.get("mode"), "LINK_EXISTING");
  const onboarding = { ...batch, warnings: [{ message: "Numeric" }], preview_payload: { ...batch.preview_payload, mode: "ONBOARD_MISSING" } };
  assert.equal(operations.canConfirmTerminalImport(onboarding, true), false);
  assert.equal(operations.canConfirmTerminalImport(onboarding, true, Date.now(), "Verified", false), false);
  assert.equal(operations.canConfirmTerminalImport(onboarding, true, Date.now(), " ", true), false);
  assert.equal(operations.canConfirmTerminalImport(onboarding, true, Date.now(), "Verified", true), true);
  for (const [category, group] of [["CREATE_PERSON_SUBAGENT_TERMINAL", "New"], ["UNCHANGED", "Unchanged"], ["NAME_CONFLICT", "Conflict"], ["INVALID", "Invalid"]]) assert.equal(operations.importRowGroup(category), group);
});

test("grouped messages render Excel rows even when message text is absent or a dash", () => {
  const warnings = [
    { row: 4, field: "SUB AGT NOS", message: "" },
    { row: 71, field: "SUB AGT NOS", message: "-" },
    { row: 76, field: "TERMINAL NOS" },
    { cell: "C80", field: "TERMINAL NOS" },
  ];
  const errors = [{ row: 72, category: "NAME_CONFLICT", detail: "NAME does not match the database person." },
    { row: 75, category: "NAME_CONFLICT", detail: "NAME does not match the database person." }];
  const groups = operations.groupImportMessages(warnings);
  assert.equal(operations.groupImportMessages([{ row: 8, category: "INVALID", message: "-" }])[0].label, "INVALID");
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].rows.map((item) => item.row), [4, 71]);
  assert.equal(groups[0].rows[0].message, "Row 4: SUB AGT NOS is numeric and may have lost leading zeroes.");
  const preview = { ...batch, errors, warnings, preview_payload: { ...batch.preview_payload, ignored_blank_rows: 69 } };
  const html = harness({ uploadPage: true, preview }).html();
  for (const row of [4, 71, 72, 75, 76, 80]) assert.match(html, new RegExp(`Row ${row}:`));
  assert.match(html, /Ignored blank template rows: 69/);
  assert.doesNotMatch(html, /<li>\s*[-–—]?\s*<\/li>/);
  assert.equal(operations.canConfirmTerminalImport(preview, true, Date.now(), "Verified", true), false);
});

test("partial policy is previewed, exclusions render exact rows and confirmation posts acknowledgements and counts", async () => {
  const partial = { ...batch, errors: [{ row: 8, category: "INCOMPLETE", detail: "NAME is required." }],
    preview_payload: { mode: "ONBOARD_MISSING", policy: "PARTIAL", valid_count: 1, excluded_count: 1,
      creation_counts: { people: 1, sub_agent_numbers: 1, terminals: 1 }, excluded_counts: { INCOMPLETE: 1 },
      rows: [{ row: 2, classification: "CREATE_PERSON_SUBAGENT_TERMINAL", excluded: false, name: "New" },
        { row: 8, classification: "INCOMPLETE", excluded: true, sub_agent_number_value: "later", terminal_number: "t8", name: "", reasons: ["NAME is required."] }] } };
  const calls = [];
  const ui = harness({ uploadPage: true, request: async (path, options) => { calls.push([path, options]); return path.endsWith("confirm/") ? { ...partial, status: "CONFIRMED", result_counts: { imported: 1, excluded: 1, created: 1, unchanged: 0 } } : path.endsWith("preview/") ? partial : []; } });
  assert.match(ui.html(), /Require all populated rows to be valid/);
  find(ui.render(), (n) => n.type === "select" && n.props.value === "LINK_EXISTING").props.onChange({ target: { value: "ONBOARD_MISSING" } });
  const policyLabel = find(ui.render(), (n) => n.type === "label" && React.Children.toArray(n.props.children).includes("Import valid rows only and skip rows with errors"));
  find(policyLabel, (n) => n.type === "input").props.onChange({ target: { checked: true } });
  await find(ui.render(), (n) => n.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(calls[0][1].body.get("policy"), "PARTIAL");
  const html = ui.html();
  assert.match(html, /Row 8/);
  assert.match(html, /NAME is required\./);
  assert.match(html, /1 rows will be excluded and only 1 valid rows will be imported/);
  assert.match(html, /Acknowledge the excluded and valid row counts/);
  for (const label of ["Valid", "Excluded", "Conflict", "Warning", "All"]) assert.match(html, new RegExp(`<option[^>]*>${label}</option>`));
  assert.equal(operations.canConfirmTerminalImport(partial, true, Date.now(), "Reason", true, false), false);
  assert.equal(operations.canConfirmTerminalImport(partial, true, Date.now(), "Reason", true, true), true);
  assert.equal(operations.canConfirmTerminalImport({ ...partial, preview_payload: { ...partial.preview_payload, valid_count: 0 } }, true, Date.now(), "Reason", true, true), false);
  find(ui.render(), (n) => n.type === "textarea").props.onChange({ target: { value: "Verified" } });
  for (const text of ["I reviewed the selected agency", "I understand that"]) {
    const label = find(ui.render(), (n) => n.type === "label" && React.Children.toArray(n.props.children).some((c) => typeof c === "string" && c.startsWith(text)));
    find(label, (n) => n.type === "input").props.onChange({ target: { checked: true } });
  }
  const confirm = find(ui.render(), (n) => n.type === "button" && n.props.children === "Confirm import");
  assert.equal(confirm.props.disabled, false);
  await confirm.props.onClick();
  const payload = JSON.parse(calls.find(([path]) => path.endsWith("confirm/"))[1].body);
  assert.equal(payload.expected_valid_count, 1);
  assert.equal(payload.expected_excluded_count, 1);
  assert.equal(payload.exclusions_acknowledged, true);
  assert.deepEqual(payload.acknowledged_counts, partial.preview_payload.creation_counts);
  assert.equal(payload.reason, "Verified");
  assert.match(ui.html(), /1 imported, 1 excluded/);
  assert.equal(operations.matchesImportFilter(partial.preview_payload.rows[0], "Valid"), true);
  assert.equal(operations.matchesImportFilter(partial.preview_payload.rows[1], "Excluded"), true);
  assert.equal(operations.matchesImportFilter(partial.preview_payload.rows[1], "Warning", [{ row: 8 }]), true);
});

test("exclusion Excel download has a controlled GET-only binary path", () => {
  assert.equal(isAllowedBackendProxyPath("terminal-number-imports/12/exclusions", "GET"), true);
  assert.equal(isBinaryBackendProxyPath("terminal-number-imports/12/exclusions", "GET"), true);
  for (const method of ["POST", "PATCH", "DELETE"]) assert.equal(isAllowedBackendProxyPath("terminal-number-imports/12/exclusions", method), false);
  assert.equal(isAllowedBackendProxyPath("terminal-number-imports/12/exclusions/extra", "GET"), false);
  assert.doesNotMatch(harness({ uploadPage: true, user: { role: "ACCOUNTANT" } }).html(), /Import valid rows only/);
});
