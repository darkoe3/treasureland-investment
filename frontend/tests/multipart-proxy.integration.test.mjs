import assert from "node:assert/strict";
import { createServer } from "node:http";
import { Readable } from "node:stream";
import { once } from "node:events";
import test from "node:test";
import { controlledBackendProxyResponse, logProxyDiagnostics } from "../lib/backend-proxy.js";
import { backendRequestWithFetchResponse } from "../lib/backend-request.js";
import { clientRequest, resetClientApiStateForTests } from "../lib/client-api.js";
import { validateCsrf } from "../lib/csrf.js";
import { UPLOAD_SERVICE_ERROR } from "../lib/request-errors.js";

const fileBytes = Buffer.from([0x50, 0x4b, 3, 4, 0, 255, 128, 13, 10, 0, 42, 17, 0x50, 0x4b, 5, 6]);
const secrets = { access: "private-access-jwt", refresh: "private-refresh-jwt", csrf: "private-csrf-value", filename: "private-workbook.xlsx" };
function formData() {
  const form = new FormData();
  form.set("agency", "7");
  form.set("transaction_date", "2026-09-10");
  form.set("file", new Blob([fileBytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), secrets.filename);
  return form;
}
async function server(t, handler) {
  const instance = createServer((req, res) => { Promise.resolve(handler(req, res)).catch(() => { res.writeHead(500); res.end(); }); });
  instance.listen(0, "127.0.0.1");
  await once(instance, "listening");
  t.after(() => { instance.closeAllConnections(); return new Promise((resolve) => instance.close(resolve)); });
  return { instance, url: `http://127.0.0.1:${instance.address().port}` };
}
async function fixture(t, config = {}) {
  const received = [], incoming = [], logs = [];
  let upstreamRequests = 0, refreshes = 0, calls = 0;
  const upstream = await server(t, async (req, res) => {
    upstreamRequests++;
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks);
    const type = req.headers["content-type"];
    const form = type?.startsWith("multipart/form-data") ? await new Response(body, { headers: { "content-type": type } }).formData() : null;
    received.push({ url: req.url, method: req.method, headers: req.headers, body, form });
    if (config.hang) return;
    const status = config.expired && req.headers.authorization === `Bearer ${secrets.access}` ? 401 : config.status || 201;
    const payload = status === 401 ? { detail: "Token expired." } : config.payload || { id: 12, preview_payload: { rows: [] } };
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(payload));
  });
  const oldBase = process.env.API_BASE_URL, oldDebug = process.env.TL_PROXY_DEBUG;
  process.env.API_BASE_URL = `${upstream.url}/api`;
  process.env.TL_PROXY_DEBUG = "1";
  t.after(() => {
    if (oldBase === undefined) delete process.env.API_BASE_URL; else process.env.API_BASE_URL = oldBase;
    if (oldDebug === undefined) delete process.env.TL_PROXY_DEBUG; else process.env.TL_PROXY_DEBUG = oldDebug;
  });
  const proxy = await server(t, async (req, res) => {
    if (req.url === "/api/auth/csrf") { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify({ csrfToken: secrets.csrf })); return; }
    if (req.url === "/api/auth/refresh") {
      refreshes++;
      assert.equal(req.headers["x-csrf-token"], secrets.csrf);
      res.writeHead(200, { "content-type": "application/json", "set-cookie": "tl_access=rotated-private-access; HttpOnly; Path=/" });
      res.end(JSON.stringify({ detail: "Session refreshed." })); return;
    }
    const headers = new Headers(req.headers);
    if (config.staleLength) {
      headers.set("content-length", "1");
      headers.set("host", "unsafe.invalid");
      headers.set("connection", "keep-alive, x-private");
      headers.set("transfer-encoding", "chunked");
      headers.set("authorization", "Bearer browser-forged");
    }
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    const request = new Request(`http://localhost${req.url}`, { method: req.method, headers, body: Readable.toWeb(req), duplex: "half" });
    const read = request.arrayBuffer.bind(request);
    let reads = 0;
    request.arrayBuffer = () => { reads++; return read(); };
    request.formData = () => { throw new Error("The proxy must not reconstruct FormData"); };
    const cookieValues = Object.fromEntries((req.headers.cookie || "").split("; ").filter(Boolean).map((part) => part.split("=")));
    const response = await controlledBackendProxyResponse(request, { params: Promise.resolve({ path: req.url.split("?")[0].replace("/api/backend/", "").split("/") }) }, {
      cookieStore: { get: (name) => ({ value: cookieValues[name] }) }, validateCsrf,
      backendRequest: async (path, options) => {
        calls++;
        return backendRequestWithFetchResponse(path, { ...options, headers: { ...options.headers, Authorization: `Bearer ${cookieValues.tl_access}` } }, fetch, config.timeout || 10000);
      },
      onDiagnostics: (diagnostic) => logProxyDiagnostics(diagnostic, { info: (label, data) => logs.push({ label, data }), warn: (label, data) => logs.push({ label, data }) }),
    });
    incoming.push({ body: Buffer.concat(chunks), contentType: req.headers["content-type"], reads });
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(Buffer.from(await response.arrayBuffer()));
  });
  let access = secrets.access;
  const browserFetch = async (path, options = {}) => {
    const headers = new Headers(options.headers);
    headers.set("cookie", `tl_access=${access}; tl_refresh=${secrets.refresh}; tl_csrf=${secrets.csrf}`);
    const response = await fetch(`${proxy.url}${path}`, { ...options, headers });
    if (path === "/api/auth/refresh" && response.ok) access = "rotated-private-access";
    return response;
  };
  const upload = (path = "/api/backend/daily-sheet-imports/preview", csrf = true) => browserFetch(path, { method: "POST", body: formData(), headers: csrf ? { "x-csrf-token": secrets.csrf } : {} });
  return { upstream, proxy, received, incoming, logs, browserFetch, upload, counts: () => ({ upstreamRequests, refreshes, calls }) };
}
function assertMultipart(record) {
  assert.equal(record.method, "POST");
  assert.equal(record.url, "/api/daily-sheet-imports/preview/");
  assert.equal(record.form.get("agency"), "7");
  assert.equal(record.form.get("transaction_date"), "2026-09-10");
  assert.equal(record.form.get("file").name, secrets.filename);
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/.exec(record.headers["content-type"]);
  assert.ok(boundary);
  assert.ok(record.body.includes(Buffer.from(`--${boundary[1] || boundary[2]}`)));
  assert.equal(Number(record.headers["content-length"]), record.body.length);
}

test("real HTTP multipart forwarding preserves exact bytes, fields, boundary and Django URL", async (t) => {
  const f = await fixture(t, { staleLength: true });
  const response = await f.upload();
  assert.equal(response.status, 201);
  assertMultipart(f.received[0]);
  assert.deepEqual(Buffer.from(await f.received[0].form.get("file").arrayBuffer()), fileBytes);
  assert.deepEqual(f.received[0].body, f.incoming[0].body);
  assert.equal(f.received[0].headers["content-type"], f.incoming[0].contentType);
  assert.equal(f.incoming[0].reads, 1);
  assert.notEqual(f.received[0].headers["content-length"], "1");
  assert.notEqual(f.received[0].headers.host, "unsafe.invalid");
  assert.equal(f.received[0].headers["transfer-encoding"], undefined);
  assert.notEqual(f.received[0].headers.connection, "keep-alive, x-private");
  assert.equal(f.received[0].headers.authorization, `Bearer ${secrets.access}`);
  assert.equal(f.received[0].headers.cookie, undefined);
  assert.equal(f.received[0].headers["x-csrf-token"], undefined);
  assert.equal(f.counts().calls, 1);
});

test("real HTTP proxy still enforces CSRF and the exact allowlist before reading/forwarding", async (t) => {
  const f = await fixture(t);
  assert.equal((await f.upload(undefined, false)).status, 403);
  assert.equal((await f.upload("/api/backend/arbitrary/private-secret?token=private-query")).status, 404);
  assert.equal(f.counts().upstreamRequests, 0);
  assert.ok(f.incoming.every((entry) => entry.reads === 0));
  assert.equal(f.logs[1].data.normalizedPath, null);
  assert.ok(!JSON.stringify(f.logs).includes("private-secret"));
});

for (const status of [400, 401, 403, 409, 422]) {
  test(`real HTTP backend ${status} validation status/body survives unchanged`, async (t) => {
    const payload = { file: ["The workbook contains invalid rows."], agency: ["Check the agency."] };
    const f = await fixture(t, { status, payload });
    const response = await f.upload();
    assert.equal(response.status, status);
    assert.match(response.headers.get("content-type"), /application\/json/);
    assert.deepEqual(await response.json(), status === 401 ? { detail: "Token expired." } : payload);
    assert.equal(f.counts().calls, 1);
  });

test("real backend 500 safe reference survives unchanged", async (t) => {
  const payload = { detail: "The import could not be confirmed. No transactions were written. Reference: abc123" };
  const f = await fixture(t, { status: 500, payload });
  const response = await f.upload();
  assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), payload);
});
}

test("confirmation JSON preserves the safe Django reference through proxy and client error", async (t) => {
  resetClientApiStateForTests();
  t.after(resetClientApiStateForTests);
  const payload = { detail: "The import could not be confirmed. No transactions were written. Reference: 46b65edee8e9" };
  const f = await fixture(t, { status: 500, payload });
  const body = JSON.stringify({ replace_existing: false, acknowledge_date_mismatch: false });
  await assert.rejects(
    clientRequest("/api/backend/daily-sheet-imports/12/confirm/", { method: "POST", body }, f.browserFetch),
    (error) => {
      assert.equal(error.status, 500);
      assert.equal(error.message, payload.detail);
      assert.deepEqual(error.payload, payload);
      return true;
    },
  );
  assert.equal(f.counts().calls, 1);
  assert.equal(f.received[0].url, "/api/daily-sheet-imports/12/confirm/");
  assert.equal(f.received[0].body.toString(), body);
  assert.equal(f.received[0].headers.cookie, undefined);
  assert.equal(f.received[0].headers["x-csrf-token"], undefined);
});

test("real connection failure maps to a safe 504 and retains only safe cause diagnostics", async (t) => {
  const f = await fixture(t);
  await new Promise((resolve) => f.upstream.instance.close(resolve));
  const response = await f.upload();
  assert.equal(response.status, 504);
  assert.deepEqual(await response.json(), { detail: UPLOAD_SERVICE_ERROR });
  assert.equal(f.logs[0].data.errorName, "TypeError");
  assert.equal(f.logs[0].data.causeCode, "ECONNREFUSED");
  assert.equal(f.counts().calls, 1);
});

test("real upstream timeout preserves AbortError evidence without disclosing the exception", async (t) => {
  const f = await fixture(t, { hang: true, timeout: 60 });
  const response = await f.upload();
  assert.equal(response.status, 504);
  assert.deepEqual(await response.json(), { detail: UPLOAD_SERVICE_ERROR });
  assert.equal(f.logs[0].data.errorName, "AbortError");
  assert.ok(f.logs[0].data.elapsedMs >= 40);
});

test("real browser refresh retries original FormData once and only the authenticated preview succeeds", async (t) => {
  resetClientApiStateForTests();
  const f = await fixture(t, { expired: true });
  const form = formData();
  const result = await clientRequest("/api/backend/daily-sheet-imports/preview", { method: "POST", body: form, headers: { "Content-Type": "multipart/form-data; boundary=wrong", "Content-Length": "1" } }, f.browserFetch);
  assert.equal(result.id, 12);
  assert.deepEqual(f.counts(), { upstreamRequests: 2, refreshes: 1, calls: 2 });
  for (const record of f.received) {
    assertMultipart(record);
    assert.deepEqual(Buffer.from(await record.form.get("file").arrayBuffer()), fileBytes);
  }
  assert.equal(f.received.filter((r) => r.headers.authorization === "Bearer rotated-private-access").length, 1);
  assert.ok(f.incoming.every((entry) => entry.reads === 1));
});

test("real validation errors display readable messages rather than raw JSON", async (t) => {
  resetClientApiStateForTests();
  const f = await fixture(t, { status: 400, payload: { file: ["Choose a valid workbook."] } });
  await assert.rejects(clientRequest("/api/backend/daily-sheet-imports/preview", { method: "POST", body: formData() }, f.browserFetch), (error) => {
    assert.equal(error.message, "Choose a valid workbook.");
    assert.equal(error.status, 400);
    return true;
  });
  assert.equal(f.counts().calls, 1);
});

test("logs contain only approved diagnostics, never credentials, boundaries, filenames or bytes", async (t) => {
  const f = await fixture(t, { status: 400 });
  await f.upload();
  const serialized = JSON.stringify(f.logs);
  for (const secret of Object.values(secrets)) assert.ok(!serialized.includes(secret));
  assert.ok(!serialized.includes(fileBytes.toString("base64")));
  assert.ok(!serialized.includes("http://"));
  assert.ok(!serialized.includes("boundary="));
  assert.deepEqual(Object.keys(f.logs[0].data).sort(), ["method", "normalizedPath", "mediaType", "hasMultipartBoundary", "bodyPresent", "bodyByteLength", "errorName", "errorCode", "causeCode", "elapsedMs"].sort());
  assert.equal(f.logs[0].data.bodyByteLength, f.received[0].body.length);
});
