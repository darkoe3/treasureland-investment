import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createRequire } from "node:module";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as icons from "lucide-react";
import * as clientApi from "../lib/client-api.js";
import * as shared from "../lib/phase4-operations.js";
import * as operations from "../lib/people-tpm-operations.js";

const { defaultPeopleFilters, filterPeople, codeActions, fieldErrors, editorRequest, submitPeopleEditor, changeCodeStatus } = operations;
const require = createRequire(import.meta.url);
const { transformSync } = require("next/dist/build/swc");
const source = await readFile(new URL("../components/PeopleTpmClient.js", import.meta.url), "utf8");
const compiled = transformSync(source, { filename: "PeopleTpmClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
const detail = "Sub-Agent Number 123456 already exists and is assigned to Ayo. Edit the existing Sub-Agent Number instead.";
const admin = { role: "SUPER_ADMIN" };
const agencies = [{ id: 1, name: "Musa" }, { id: 2, name: "Sango" }];
const activeCode = { id: 4, code: "123456", is_active: true };
const inactiveCode = { id: 5, code: "ABC-789", is_active: false };
const person = { id: 1, full_name: "Ayo", agency: 1, agency_name: "Musa", is_active: true, agent_type: "MAIN_AGENT", tpm_codes: [activeCode, inactiveCode] };
const target = { id: 2, full_name: "Bisi", agency: 1, agency_name: "Musa", is_active: false, agent_type: "SUBAGENT", tpm_codes: [] };
const hidden = { ...target, id: 3, full_name: "Hidden", agency: 2, agency_name: "Sango" };
const people = [person, target, hidden];
const accountant = (flags = {}) => ({ role: "ACCOUNTANT", agency_assignments: [{ agency: { id: 1 }, ...flags }] });

// Exercise the actual component's handlers and rendered markup with deterministic hook state.
// This does not substitute for browser layout/keyboard testing.
function harness({ user = admin, editor = null, draft = {}, status = {}, request = async () => people } = {}) {
  const states = [people, { ...defaultPeopleFilters }, editor, draft, {}, { loading: false, error: "", success: "", ...status }, false];
  const refs = [];
  let stateIndex = 0, refIndex = 0;
  const fakeReact = { ...React, useState(initial) {
    const index = stateIndex++;
    if (!(index in states)) states[index] = initial;
    return [states[index], (value) => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
  }, useRef(initial) { const index = refIndex++; return refs[index] ||= { current: initial }; }, useMemo(fn) { return fn(); }, useEffect() {} };
  const compiledModule = { exports: {} };
  vm.runInNewContext(compiled, { module: compiledModule, exports: compiledModule.exports, require(name) {
    if (name === "react") return fakeReact;
    if (name === "react/jsx-runtime") return require(name);
    if (name === "lucide-react") return icons;
    if (name === "../lib/client-api") return { ...clientApi, clientRequest: request };
    if (name === "../lib/phase4-operations") return shared;
    if (name === "../lib/people-tpm-operations") return operations;
    throw new Error(`Unexpected test import ${name}`);
  }, window: { confirm: () => true } });
  const render = () => { stateIndex = 0; refIndex = 0; return compiledModule.exports.default({ user, initialAgencies: agencies }); };
  return { states, render, html: () => renderToStaticMarkup(render()) };
}
function nodes(node) {
  if (!React.isValidElement(node)) return [];
  if (typeof node.type === "function") return nodes(node.type(node.props));
  return [node, ...React.Children.toArray(node.props.children).flatMap(nodes)];
}
function find(tree, predicate) { const result = nodes(tree).find(predicate); assert.ok(result, "Expected element in rendered component"); return result; }
const clickEvent = { currentTarget: { isConnected: false }, preventDefault() {} };

test("client displays Django validation safely and supplies field messages", async () => {
  clientApi.resetClientApiStateForTests();
  const fetchImpl = async (path) => path === "/api/auth/csrf"
    ? new Response(JSON.stringify({ csrfToken: "test-csrf" }), { status: 200 })
    : new Response(JSON.stringify({ code: [detail] }), { status: 400 });
  await assert.rejects(clientApi.clientRequest("/api/backend/tpm-codes/", { method: "POST", body: "{}" }, fetchImpl), (error) => {
    assert.equal(error.message, detail);
    assert.equal(fieldErrors(error).code, detail);
    return true;
  });
  assert.deepEqual(fieldErrors({ status: 500, payload: { detail: "private traceback" } }), {});
  assert.equal(clientApi.validationMessage({ detail: "private traceback" }, 500), "Upstream service error.");
  assert.equal(clientApi.validationMessage({ detail: "Reference: abc123" }, 500), "Reference: abc123");
});

test("active and inactive Sub-Agent Numbers have separate appropriate actions", () => {
  assert.deepEqual(codeActions(admin, person, activeCode), ["edit", "reassign", "deactivate"]);
  assert.deepEqual(codeActions(admin, person, inactiveCode), ["edit", "reassign", "reactivate"]);
  const html = harness().html();
  for (const label of ["Edit Sub-Agent Number 123456", "Reassign Sub-Agent Number 123456", "Deactivate Sub-Agent Number 123456", "Reactivate Sub-Agent Number ABC-789"]) assert.ok(html.includes(label));
  assert.ok(!html.includes("Deactivate Sub-Agent Number ABC-789"));
  assert.ok(!html.includes("Reactivate Sub-Agent Number 123456"));
  assert.match(html, /people-status is-inactive/);
});

test("accountants only see accessible agencies and independently permitted actions", () => {
  assert.deepEqual(codeActions(accountant(), person, activeCode), []);
  assert.deepEqual(codeActions(accountant({ can_delete: true }), person, activeCode), ["deactivate"]);
  assert.deepEqual(codeActions(accountant({ can_edit: true }), person, inactiveCode), ["edit", "reassign", "reactivate"]);
  const readonly = harness({ user: accountant() }).html();
  assert.ok(!readonly.includes("Hidden") && !readonly.includes("Sango"));
  assert.ok(!readonly.includes("Edit Sub-Agent Number") && !readonly.includes("Add Person"));
  const editable = harness({ user: accountant({ can_edit: true }) }).html();
  assert.ok(editable.includes("Reassign Sub-Agent Number 123456"));
  assert.ok(!editable.includes("Deactivate Sub-Agent Number 123456"));
  assert.ok(!editable.includes("Add Person"));
});

test("filters combine name/code, agency, person status and inactive code visibility", () => {
  assert.equal(filterPeople(people, { ...defaultPeopleFilters, query: "abc-789" })[0].visibleCodes[0].id, 5);
  assert.deepEqual(filterPeople(people, { ...defaultPeopleFilters, query: "abc-789", showInactive: false }), []);
  assert.equal(filterPeople(people, { ...defaultPeopleFilters, query: "AYO", agency: "1", status: "active" }).length, 1);
  assert.deepEqual(filterPeople(people, { ...defaultPeopleFilters, agency: "2", status: "active" }), []);
  assert.equal(filterPeople(people, { ...defaultPeopleFilters, agency: "1", status: "inactive" })[0].id, 2);
  const ui = harness();
  find(ui.render(), (n) => n.props.id === "people-search").props.onChange({ target: { value: "unknown" } });
  assert.match(ui.html(), /No people match your filters/);
  find(ui.render(), (n) => n.type === "button" && n.props.onClick?.name === "resetFilters").props.onClick();
  assert.deepEqual({ ...ui.states[1] }, defaultPeopleFilters);
  assert.match(ui.html(), /3 matching people/);
});

test("Edit cannot change ownership; Reassign shows current and new owner details", () => {
  assert.deepEqual(editorRequest({ kind: "code", person, code: activeCode }, { code: "NEW", person: 2, is_active: false }).payload, { code: "NEW" });
  const ui = harness();
  find(ui.render(), (n) => n.props["aria-label"] === "Edit Sub-Agent Number 123456").props.onClick(clickEvent);
  assert.ok(!ui.html().includes('id="people-person"'));
  assert.match(ui.html(), /Edit Sub-Agent Number/);
  const reassign = harness({ editor: { kind: "reassign", person, code: inactiveCode }, draft: { person: 2, is_active: true } }).html();
  for (const label of ["Current person", "Current agency", "Current status", "New person", "New agency", "Sub-Agent status after saving", "ABC-789"]) assert.ok(reassign.includes(label));
});

test("confirmation is required before reassignment and describes both people", async () => {
  const editor = { kind: "reassign", person, code: inactiveCode };
  const draft = { person: 2, is_active: true };
  const requests = [];
  const request = async (path, options) => requests.push({ path, ...options });
  const confirm = (accept) => (message) => { assert.match(message, /ABC-789.*Ayo \(Musa\).*Bisi \(Musa\)/); assert.match(message, /active/); return accept; };
  assert.equal(await submitPeopleEditor(editor, draft, people, request, confirm(false)), null);
  assert.equal(requests.length, 0);
  await submitPeopleEditor(editor, draft, people, request, confirm(true));
  assert.deepEqual(JSON.parse(requests[0].body), { person: 2, is_active: true, confirm_reassignment: true });
  await assert.rejects(submitPeopleEditor(editor, { person: 1 }, people, request, confirm(true)), /different person/);
});

test("reactivation only patches status and deactivation requires confirmation", async () => {
  const requests = [];
  const request = async (path, options) => requests.push({ path, ...options });
  assert.equal(await changeCodeStatus(person, activeCode, request, () => false), null);
  assert.equal(requests.length, 0);
  assert.match(await changeCodeStatus(person, activeCode, request, (message) => { assert.match(message, /123456 assigned to Ayo/); return true; }), /deactivated/);
  assert.equal(requests[0].method, "DELETE");
  assert.match(await changeCodeStatus(person, inactiveCode, request, () => { throw new Error("Unexpected confirmation"); }), /reactivated/);
  assert.deepEqual(JSON.parse(requests[1].body), { is_active: true });
});

test("loading and saving disable actions, block duplicate submissions and retain failed values", async () => {
  const loading = harness({ status: { loading: true } });
  for (const n of nodes(loading.render()).filter((n) => n.type === "button" && n.props.onClick?.name !== "resetFilters")) assert.equal(n.props.disabled, true);
  let rejectSave, calls = 0;
  const ui = harness({ editor: { kind: "code", person: null, code: null }, draft: { code: "123456", person: 1, is_active: true }, request: async () => { calls++; return new Promise((resolve, reject) => { rejectSave = reject; }); } });
  const form = find(ui.render(), (n) => n.type === "form");
  const saving = form.props.onSubmit(clickEvent);
  await form.props.onSubmit(clickEvent);
  assert.equal(calls, 1);
  assert.match(ui.html(), /Saving/);
  assert.equal(find(ui.render(), (n) => n.type === "fieldset").props.disabled, true);
  rejectSave(new clientApi.ClientApiError(detail, 400, { code: [detail] }));
  await saving;
  const html = ui.html();
  assert.match(html, /value="123456"/);
  assert.ok(html.includes(detail));
  assert.match(html, /aria-describedby="people-code-error"/);
  assert.match(html, /id="people-code-error"/);
  assert.equal(ui.states[6], false);
});

test("successful operations close the panel and announce success after refresh", async () => {
  const ui = harness({ editor: { kind: "person", person: null }, draft: { full_name: "New Person", agency: 1, agent_type: "MAIN_AGENT", is_active: true } });
  await find(ui.render(), (n) => n.type === "form").props.onSubmit(clickEvent);
  assert.equal(ui.states[2], null);
  assert.match(ui.html(), /Person created/);
});

test("page-scoped layout wraps controls without scaling and provides keyboard focus", async () => {
  const css = (await readFile(new URL("../app/globals.css", import.meta.url), "utf8")).split("/* People & Sub-Agent Numbers:")[1];
  assert.match(css, /min-width: 0/);
  assert.match(css, /overflow-wrap: anywhere/);
  assert.match(css, /flex-wrap: wrap/);
  assert.match(css, /max-width: 1100px/);
  assert.match(css, /max-width: 600px/);
  assert.match(css, /minmax\(0, 1fr\)/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /scroll-margin-top/);
  assert.doesNotMatch(css, /zoom:|scale\(/);
  assert.match(source, /editorHeading.current\?\.focus/);
  assert.match(source, /trigger.current.isConnected/);
  assert.match(harness().html(), /<label for="people-search">/);
});
