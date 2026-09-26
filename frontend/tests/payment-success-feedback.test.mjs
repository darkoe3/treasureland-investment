import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as icons from "lucide-react";
import * as clientApi from "../lib/client-api.js";
import * as operations from "../lib/payment-operations.js";

const require = createRequire(import.meta.url);
const { transformSync } = require("next/dist/build/swc");
const source = await readFile(new URL("../components/PaymentsClient.js", import.meta.url), "utf8");
const compiled = transformSync(source, { filename: "PaymentsClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;

const admin = { role: "SUPER_ADMIN" };
const agency = { id: 1, name: "Musa" };
const partialObligation = { id: 5, agency: 1, agency_name: "Musa", payer_name: "Ayo", obligation_number: "TLI-OBL-000005", description: "Weekly dues", total_expected: "100.00", total_paid: "40.00", reversed_total: "0.00", balance: "60.00", status: "PARTIALLY_PAID", obligation_date: "2026-01-01" };
const refreshedObligation = { ...partialObligation, total_paid: "80.00", balance: "20.00" };
const paidObligation = { ...partialObligation, total_paid: "100.00", balance: "0.00", status: "PAID" };
const createdPayment = { id: 9, obligation: 5, receipt_number: "TLI-PAY-000009", amount_received: "40.00", status: "POSTED" };
const EMPTY_PAYMENT = { amount_received: "", payment_method: "CASH", payment_reference: "", notes: "", payment_date: "" };

// Compiles the real component and runs it with deterministic hook slots so state transitions
// (success/close/reset) can be exercised without a browser or testing-library dependency.
function harness({ user = admin, obligation = partialObligation, payments = [], paymentOpen = false, success = null, form = { ...EMPTY_PAYMENT }, pending = false, responses = {} } = {}) {
  const states = [
    { loading: false, error: "", data: { agencies: [agency], obligation, payments } },
    paymentOpen,
    false,
    success,
    "",
    form,
    "",
    {},
    pending,
  ];
  const refs = [];
  const calls = [];
  let stateIndex = 0, refIndex = 0;
  async function request(path, options = {}) {
    calls.push([path, options]);
    const method = (options.method || "GET").toUpperCase();
    const key = `${method} ${path.split("?")[0]}`;
    const handler = responses[key];
    if (!handler) throw new Error(`Unexpected test request ${key}`);
    return typeof handler === "function" ? handler(options) : handler;
  }
  const fakeReact = { ...React,
    useState(initial) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
      return [states[index], (value) => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
    },
    useRef(initial) { const index = refIndex++; return refs[index] ||= { current: initial }; },
    useCallback(fn) { return fn; },
    useMemo(fn) { return fn(); },
    useEffect() {},
  };
  const compiledModule = { exports: {} };
  vm.runInNewContext(compiled, { module: compiledModule, exports: compiledModule.exports, URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} }, document: { createElement: () => ({ click() {} }) }, setTimeout, require(name) {
    if (name === "react") return fakeReact;
    if (name === "react/jsx-runtime") return require(name);
    if (name === "lucide-react") return icons;
    if (name === "next/link") return { __esModule: true, default: (props) => require("react/jsx-runtime").jsx("a", { href: props.href, className: props.className, children: props.children }) };
    if (name === "../lib/client-api") return { ...clientApi, clientRequest: request, clientDownload: async () => ({ blob: {}, contentType: "application/pdf", contentDisposition: "" }) };
    if (name === "../lib/payment-operations") return operations;
    throw new Error(`Unexpected test import ${name}`);
  } });
  const render = () => { stateIndex = 0; refIndex = 0; return compiledModule.exports.default({ user, view: "obligation", recordId: obligation.id }); };
  return { states, refs, calls, render, html: () => renderToStaticMarkup(render()) };
}

function nodes(node) {
  if (!React.isValidElement(node)) return [];
  if (typeof node.type === "function") return nodes(node.type(node.props));
  return [node, ...React.Children.toArray(node.props.children).flatMap(nodes)];
}
function find(tree, predicate) { const result = nodes(tree).find(predicate); assert.ok(result, "Expected element in rendered component"); return result; }
const submitEvent = { preventDefault() {} };

test("successful payment closes the form, resets fields, and refreshes obligation totals and history", async () => {
  const ui = harness({
    paymentOpen: true,
    form: { amount_received: "40.00", payment_method: "CASH", payment_reference: "", notes: "", payment_date: "2026-01-05" },
    responses: {
      "POST /api/backend/payer-payments/": createdPayment,
      "GET /api/backend/agencies/": [agency],
      "GET /api/backend/payment-obligations/5/": refreshedObligation,
      "GET /api/backend/payer-payments/": [createdPayment],
    },
  });
  const formNode = find(ui.render(), (node) => node.type === "form");
  await formNode.props.onSubmit(submitEvent);
  // onRefresh() is fire-and-forget from the success handler; flush the microtask queue so its
  // internal awaits (agencies, obligation, payment history) resolve before asserting on ui.calls.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(ui.states[1], false, "the payment form closes after confirmed success");
  // Spread into a host-realm plain object first: the sandboxed module's own object literal has a
  // different Object.prototype, which would otherwise fail a strict prototype-aware deep comparison.
  assert.deepEqual({ ...ui.states[5] }, EMPTY_PAYMENT, "form fields reset after confirmed success");
  assert.deepEqual(ui.states[3], createdPayment, "success state captures the created payment for the banner");
  assert.ok(ui.calls.some(([path]) => path.includes("payment-obligations/5/")), "obligation totals/status refresh after success");
  assert.ok(ui.calls.some(([path]) => path.includes("payer-payments/") && path.includes("?")), "payment history refresh after success");
});

test("success banner shows amount, receipt number, balance, status, download and record-another for a partial payment", async () => {
  const ui = harness({ obligation: refreshedObligation, success: createdPayment });
  const html = ui.html();
  assert.match(html, /Payment recorded successfully\./);
  assert.match(html, /GH₵ 40\.00/);
  assert.match(html, /TLI-PAY-000009/);
  assert.match(html, /GH₵ 20\.00/);
  assert.match(html, /POSTED/);
  assert.match(html, /Download receipt/);
  assert.match(html, /Record another payment/);
  assert.match(html, /tabindex="-1"/);
  assert.match(html, /role="status"/);
  assert.match(html, /aria-live="polite"/);
});

test("fully paid obligation shows Obligation fully paid and hides Record another payment and the header action", async () => {
  const ui = harness({ obligation: paidObligation, success: { ...createdPayment, amount_received: "20.00" } });
  const html = ui.html();
  assert.match(html, /Obligation fully paid\./);
  assert.doesNotMatch(html, /Record another payment/);
  assert.doesNotMatch(html, />Record payment<\/button>/);
});

test("failed validation keeps the form open and preserves the entered values", async () => {
  const enteredForm = { amount_received: "999.00", payment_method: "CASH", payment_reference: "", notes: "keep me", payment_date: "2026-01-05" };
  const ui = harness({
    paymentOpen: true,
    form: enteredForm,
    responses: {
      "POST /api/backend/payer-payments/": () => { const error = new Error("Amount exceeds balance."); error.status = 400; error.payload = { amount_received: ["Amount exceeds balance."] }; throw error; },
    },
  });
  const formNode = find(ui.render(), (node) => node.type === "form");
  await formNode.props.onSubmit(submitEvent);
  assert.equal(ui.states[1], true, "the form stays open on validation failure");
  assert.deepEqual(ui.states[5], enteredForm, "entered values are preserved on failure");
  assert.deepEqual(ui.states[6], { amount_received: ["Amount exceeds balance."] }, "the safe backend validation message is shown");
  assert.equal(ui.states[3], null, "no success banner appears on failure");
  assert.equal(ui.calls.length, 1, "only one attempt was sent");
});

test("pending submission is blocked from resubmitting and shows the Recording payment label", async () => {
  const ui = harness({ paymentOpen: true, pending: true });
  const html = ui.html();
  assert.match(html, /Recording payment…/);
  assert.match(html, /disabled=""/);
  const formNode = find(ui.render(), (node) => node.type === "form");
  await formNode.props.onSubmit(submitEvent);
  assert.equal(ui.calls.length, 0, "a pending submission does not fire a duplicate request");
});

test("idempotency key is reused for a retried unchanged attempt and regenerates only when values actually change", async () => {
  const ui = harness({
    paymentOpen: true,
    form: { amount_received: "40.00", payment_method: "CASH", payment_reference: "", notes: "", payment_date: "2026-01-05" },
    responses: {
      // Every attempt fails here so the form never unmounts; only the idempotency key logic is under test.
      "POST /api/backend/payer-payments/": () => { const error = new Error("Network error"); error.status = 502; throw error; },
    },
  });
  // Materialize the tree once: calling find() twice on the same unwalked tree would re-invoke
  // nested function components and drift the deterministic hook slot counters.
  const flat = nodes(ui.render());
  const formNode = flat.find((node) => node.type === "form");
  const amountInput = flat.find((node) => node.type === "input" && node.props["aria-describedby"] === "amount-error");
  assert.ok(formNode && amountInput, "expected form and amount input in rendered component");
  await formNode.props.onSubmit(submitEvent);
  const firstKey = ui.calls[0][1].body && JSON.parse(ui.calls[0][1].body).idempotency_key;
  await formNode.props.onSubmit(submitEvent);
  const secondKey = JSON.parse(ui.calls[1][1].body).idempotency_key;
  assert.equal(firstKey, secondKey, "an unchanged retry reuses the same idempotency key");
  amountInput.props.onChange({ target: { value: "55.00" } });
  await formNode.props.onSubmit(submitEvent);
  const thirdKey = JSON.parse(ui.calls[2][1].body).idempotency_key;
  assert.notEqual(secondKey, thirdKey, "changing the attempt generates a new idempotency key");
});

test("cancelling the payment form closes it without recording a payment", async () => {
  const ui = harness({ paymentOpen: true });
  const cancelButton = find(ui.render(), (node) => node.type === "button" && node.props.children === "Cancel");
  cancelButton.props.onClick();
  assert.equal(ui.states[1], false, "explicit cancellation closes the form");
  assert.equal(ui.calls.length, 0, "cancellation never submits a payment");
});

test("idempotency keys and payment identifiers are never written to browser storage", async () => {
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
});
