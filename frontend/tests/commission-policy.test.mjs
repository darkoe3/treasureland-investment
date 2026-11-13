import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import vm from "node:vm";
import { JSDOM } from "jsdom";
import { isAllowedBackendProxyPath } from "../lib/controlled-proxy-path.js";
import { controlledBackendProxyResponse } from "../lib/backend-proxy.js";
import { backendRequestWithFetchResponse } from "../lib/backend-request.js";
import * as clientApi from "../lib/client-api.js";
import * as operations from "../lib/phase4-operations.js";

const policy = "daily-sheets/commission-policy";
test("commission policy allows only GET with existing slash and query conventions", () => {
  for (const path of [policy, `${policy}/`, `/${policy}/`, `/${policy}/?agency=1`]) {
    assert.equal(isAllowedBackendProxyPath(path, "GET"), true);
    for (const method of ["POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"]) {
      assert.equal(isAllowedBackendProxyPath(path, method), false, `${method} ${path}`);
    }
  }
});

test("commission policy rejects similar paths and query-based bypasses before forwarding", async () => {
  for (const path of ["daily-sheets/commission-policies", `${policy}-extra`, `${policy}/extra`, "daily-sheets/1/commission-policy", "daily-sheets/Commission-policy", "daily-sheets/commission%2Dpolicy", "daily-sheets/private?path=daily-sheets/commission-policy/", "daily-sheets/private?../commission-policy/", "daily-sheets/private?allowed=true"]) {
    assert.equal(isAllowedBackendProxyPath(path), false, path);
    const response = await proxyFetch(`/api/backend/${path}`, {}, () => { assert.fail("Rejected path reached backend"); });
    assert.equal(response.status, 404);
  }
  for (const method of ["POST", "PATCH", "PUT", "DELETE"]) {
    const response = await proxyFetch(`/api/backend/${policy}/?method=GET`, { method }, () => { assert.fail("Rejected method reached backend"); });
    assert.equal(response.status, 404);
  }
});

test("existing controlled routes retain their method restrictions", () => {
  for (const [path, allowed, rejected] of [
    ["daily-sheets/", "POST", "PUT"], ["daily-sheets/12/", "PATCH", "PUT"],
    ["daily-sheets/12/summary/", "GET", "POST"], ["daily-sheets/12/submit/", "POST", "GET"],
    ["daily-sheet-imports/preview/", "POST", "GET"], ["reports/agency-summary/", "GET", "POST"],
    ["accountants/12/set-agencies/", "POST", "GET"], ["games/for-date/", "GET", "DELETE"],
  ]) {
    assert.equal(isAllowedBackendProxyPath(path, allowed), true);
    assert.equal(isAllowedBackendProxyPath(path, rejected), false);
  }
});

function proxyFetch(path, options = {}, upstream = async () => Response.json({ commission_rate: "0.0200" })) {
  const url = new URL(path, "http://localhost");
  return controlledBackendProxyResponse(new Request(url, options), {
    params: Promise.resolve({ path: url.pathname.replace(/^\/api\/backend\//, "").split("/") }),
  }, {
    cookieStore: {}, validateCsrf: () => true, onDiagnostics() {},
    backendRequest: (backendPath, backendOptions) => backendRequestWithFetchResponse(backendPath, backendOptions, upstream),
  });
}

test("policy forwarding restores Django trailing slash and preserves query and backend denial", async () => {
  const response = await proxyFetch(`/api/backend/${policy}/?agency=1`, {}, async (url, options) => {
    assert.equal(new URL(url).pathname, `/api/${policy}/`);
    assert.equal(new URL(url).search, "?agency=1");
    assert.equal(options.method, "GET");
    return Response.json({ detail: "Permission denied." }, { status: 403 });
  });
  assert.equal(response.status, 403);
  assert.deepEqual(await response.json(), { detail: "Permission denied." });
});

const dom = new JSDOM("<!doctype html><body></body>", { url: "http://localhost" });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import("react");
const { createRoot } = await import("react-dom/client");
const require = createRequire(import.meta.url);
const source = await readFile(new URL("../components/DailySheetsClient.js", import.meta.url), "utf8");
const compiled = require("next/dist/build/swc").transformSync(source, {
  filename: "DailySheetsClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" },
}).code;

async function mount(t, upstream) {
  clientApi.resetClientApiStateForTests();
  const calls = [];
  const mod = { exports: {} };
  vm.runInNewContext(compiled, { module: mod, exports: mod.exports, URLSearchParams, queueMicrotask, require(name) {
    if (name === "./SheetSafetyControls") return () => null;
    if (name === "next/link") return function TestLink({ children, ...props }) { return React.createElement("a", props, children); };
    if (name === "next/navigation") return { useRouter: () => ({ push() {} }) };
    if (name === "../lib/phase4-operations") return operations;
    if (name === "../lib/client-api") return { ...clientApi, clientRequest: (path, options) => clientApi.clientRequest(path, options, (url, init) => {
      calls.push(url);
      return proxyFetch(url, init, (backendUrl, backendOptions) => new URL(backendUrl).pathname.includes("commission-policy") ? upstream(backendUrl, backendOptions) : Response.json([]));
    }) };
    return require(name);
  } });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  t.after(async () => { await React.act(async () => root.unmount()); container.remove(); clientApi.resetClientApiStateForTests(); });
  await React.act(async () => { root.render(React.createElement(mod.exports.default, { user: { role: "SUPER_ADMIN" } })); });
  return { container, calls };
}

test("New Daily Sheet fetches policy through controlled proxy and displays 2%", async (t) => {
  const { container, calls } = await mount(t, async () => Response.json({ commission_rate: "0.0200" }));
  assert.ok(calls.includes(`/api/backend/${policy}/`));
  assert.match(container.textContent, /Commission: 2% of NET Sales/);
});

test("New Daily Sheet displays a safe policy backend error without credentials or tokens", async (t) => {
  const secret = "private-access-token private-refresh-token database-password";
  const upstream = async () => new Response(`<html>${secret}</html>`, { status: 500, headers: { "content-type": "text/html" } });
  const response = await proxyFetch(`/api/backend/${policy}/`, {}, upstream);
  assert.deepEqual(await response.json(), { detail: "Upstream service error." });
  const { container } = await mount(t, upstream);
  assert.doesNotMatch(container.textContent, /private-access-token|private-refresh-token|database-password/);
  for (let i = 0; i < 30 && !container.textContent.includes("Upstream service error."); i++) await React.act(async () => { await new Promise((resolve) => setTimeout(resolve, 100)); });
  assert.match(container.textContent, /Upstream service error\./);
});
