import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { buildBackendUrl, normalizeBackendPath } from "../lib/backend-url.js";
import { ApiError, backendRequestWithFetch } from "../lib/backend-request.js";
import { normalizeProxySegments, resolveBackendProxyRequest } from "../lib/backend-proxy.js";
import { ACCOUNTANT_ID_ERROR, saveAccountantWithAssignments } from "../lib/accountant-submit.js";
import { apiPath, clientDownload, clientRequest, resetClientApiStateForTests } from "../lib/client-api.js";
import { backendPathFromProxySegments, isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "../lib/controlled-proxy-path.js";
import {
  actionAvailability,
  activeTpmOptions,
  buildTransactionPayload,
  calculateTransactionPreview,
  differenceLabel,
  filterByVisibleAgency,
  listFromPayload,
  searchPeople,
} from "../lib/phase4-operations.js";
import { buildReportQuery, filenameFromDisposition, resolvePeriodDisplay, validateReportFilters } from "../lib/report-operations.js";
import { emptyScheduleForm, schedulePayload, validateScheduleForm, withScheduleMode } from "../lib/game-schedule-operations.js";
import { activeAgenciesFromPayload, buildAssignmentRows, listFromApiPayload, shouldSyncAgencyAssignments } from "../lib/resource-shapes.js";

async function file(path) {
  return readFile(new URL(`../${path}`, import.meta.url), "utf8");
}

test("auth routes avoid browser storage and token responses", async () => {
  const files = await Promise.all([
    file("app/api/auth/login/route.js"),
    file("app/api/auth/refresh/route.js"),
    file("app/api/auth/logout/route.js"),
    file("app/api/auth/me/route.js"),
    file("lib/client-api.js"),
  ]);
  const source = files.join("\n");
  assert.equal(source.includes("localStorage"), false);
  assert.equal(source.includes("sessionStorage"), false);
  assert.match(await file("app/api/auth/login/route.js"), /return NextResponse\.json\(\{ user: payload\.user \}\)/);
  assert.match(await file("app/api/auth/refresh/route.js"), /return NextResponse\.json\(\{ detail: "Session refreshed\." \}\)/);
  assert.doesNotMatch(await file("lib/client-api.js"), /ACCESS_COOKIE|REFRESH_COOKIE|Authorization/);
});

test("staging deployment keeps api base server-only and cookies secure in production", async () => {
  const envExample = await file(".env.example");
  const backendUrl = await file("lib/backend-url.js");
  const authCookies = await file("lib/auth-cookies.js");
  const clientApi = await file("lib/client-api.js");

  assert.match(envExample, /^API_BASE_URL=/m);
  assert.doesNotMatch(envExample, /^NEXT_PUBLIC_API_BASE_URL=/m);
  assert.match(backendUrl, /process\.env\.API_BASE_URL/);
  assert.doesNotMatch(clientApi, /process\.env\.API_BASE_URL|NEXT_PUBLIC_API_BASE_URL/);
  assert.match(authCookies, /secure: process\.env\.NODE_ENV === "production"/);
  assert.match(authCookies, /httpOnly: true/);
  assert.match(authCookies, /sameSite: "lax"/);
});

test("state-changing auth endpoints require csrf validation", async () => {
  assert.match(await file("app/api/auth/login/route.js"), /validateCsrf\(request, store\)/);
  assert.match(await file("app/api/auth/logout/route.js"), /validateCsrf\(request, store\)/);
  assert.match(await file("app/api/auth/refresh/route.js"), /validateCsrf\(request, store\)/);
  assert.match(await file("app/api/backend/[...path]/route.js"), /validateCsrf/);
  assert.match(await file("lib/backend-proxy.js"), /Invalid security token/);
});

test("refresh and logout handle missing or invalid sessions safely", async () => {
  const refresh = await file("app/api/auth/refresh/route.js");
  const logout = await file("app/api/auth/logout/route.js");
  const me = await file("app/api/auth/me/route.js");
  assert.match(refresh, /Missing refresh token|Session expired/);
  assert.match(logout, /clearAuthCookies\(store\)/);
  assert.match(me, /clearAuthCookies\(store\)/);
});

test("backend proxy is allowlisted and not an open proxy", async () => {
  const source = await file("app/api/backend/[...path]/route.js");
  const allowlist = await file("lib/controlled-proxy-path.js");
  assert.match(source, /resolveBackendProxyRequest/);
  assert.match(allowlist, /COLLECTION_METHODS/);
  assert.match(allowlist, /DETAIL_METHODS/);
  assert.match(allowlist, /ACCOUNTANT_ACTION_METHODS/);
  assert.match(await file("lib/backend-proxy.js"), /API path is not allowed/);
  assert.equal(source.includes("destination"), false);
});

test("protected route interception validates against backend and preserves safe next paths", async () => {
  const source = await file("proxy.js");
  assert.match(source, /auth\/me\//);
  assert.match(source, /auth\/refresh\//);
  assert.match(source, /setAuthCookies\(response\.cookies/);
  assert.match(source, /target\.startsWith\(\"\/dashboard\"\)/);
});

test("backend url builder restores Django router trailing slashes before queries", () => {
  const base = "http://127.0.0.1:8000/api/";
  assert.equal(buildBackendUrl("accountants", base), "http://127.0.0.1:8000/api/accountants/");
  assert.equal(buildBackendUrl("/accountants/7", base), "http://127.0.0.1:8000/api/accountants/7/");
  assert.equal(buildBackendUrl("/accountants/7/set-agencies", base), "http://127.0.0.1:8000/api/accountants/7/set-agencies/");
  assert.equal(buildBackendUrl("/accountants/7/reset-password?next=/dashboard", base), "http://127.0.0.1:8000/api/accountants/7/reset-password/?next=/dashboard");
  assert.equal(buildBackendUrl("/accountants?active=true&search=ada", base), "http://127.0.0.1:8000/api/accountants/?active=true&search=ada");
  assert.equal(buildBackendUrl("/api/accountants", base), "http://127.0.0.1:8000/api/accountants/");
  assert.equal(normalizeBackendPath("/accountants?active=true", base), "/accountants/?active=true");
});

test("frontend assignment save url reaches allowed proxy and normalized backend endpoint", async () => {
  const calls = [];
  const frontendPath = apiPath("accountants/7/set-agencies/");
  assert.equal(frontendPath, "/api/backend/accountants/7/set-agencies/");

  const proxyUrl = new URL(`http://localhost${frontendPath}`);
  const segments = proxyUrl.pathname.replace(/^\/api\/backend\/?/, "").split("/").filter(Boolean);
  const proxyPath = segments.join("/");
  assert.equal(isAllowedBackendProxyPath(proxyPath, "POST"), true);

  const backendPath = backendPathFromProxySegments(segments, proxyUrl.search);
  await backendRequestWithFetch(
    backendPath,
    {
      method: "POST",
      body: JSON.stringify({ agency_assignments: [{ agency: 1, can_create: true }] }),
    },
    async (url, options) => {
      calls.push({ url, options });
      return new Response(JSON.stringify({ id: 7, agency_assignments: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  );

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/accountants/7/set-agencies/");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.body, JSON.stringify({ agency_assignments: [{ agency: 1, can_create: true }] }));
});

function csrfPass() {
  return true;
}

function csrfFail() {
  return false;
}

function cookieStore() {
  return { get: () => ({ value: "csrf-token" }) };
}

function requestFor(method, path, body = "") {
  return new Request(`http://localhost${path}`, { method, body: body || undefined, headers: body ? { "x-csrf-token": "csrf-token" } : {} });
}

async function resolveProxy({ method = "POST", segments, path = null, body = "{}", validateCsrf = csrfPass, backendStatus = 200, backendPayload = { ok: true } }) {
  const calls = [];
  const requestPath = path || `/api/backend/${segments.join("/")}/`;
  const result = await resolveBackendProxyRequest(
    requestFor(method, requestPath, ["GET", "HEAD"].includes(method) ? "" : body),
    { params: Promise.resolve({ path: segments }) },
    {
      cookieStore: cookieStore(),
      validateCsrf,
      backendRequest: async (backendPath, options) => {
        calls.push({ backendPath, options, url: buildBackendUrl(backendPath) });
        return { status: backendStatus, payload: backendPayload };
      },
    },
  );
  return { result, calls };
}

test("backend proxy resolver accepts promised Next params and forwards set-agencies with trailing slash", async () => {
  const { result, calls } = await resolveProxy({ segments: ["accountants", "7", "set-agencies"] });

  assert.equal(result.status, 200);
  assert.deepEqual(result.payload, { ok: true });
  assert.equal(result.diagnostics.method, "POST");
  assert.deepEqual(result.diagnostics.paramsPath, ["accountants", "7", "set-agencies"]);
  assert.equal(result.diagnostics.normalizedPath, "accountants/7/set-agencies");
  assert.equal(result.diagnostics.allowed, true);
  assert.equal(result.diagnostics.backendUrl, "http://127.0.0.1:8000/api/accountants/7/set-agencies/");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].backendPath, "/accountants/7/set-agencies");
  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/accountants/7/set-agencies/");
  assert.equal(calls[0].options.method, "POST");
});

test("backend proxy resolver tolerates an accidental mounted api/backend prefix before allowlist comparison", async () => {
  assert.deepEqual(normalizeProxySegments(["api", "backend", "accountants", "7", "set-agencies"]), ["accountants", "7", "set-agencies"]);
  const { result, calls } = await resolveProxy({ segments: ["api", "backend", "accountants", "7", "set-agencies"] });

  assert.equal(result.status, 200);
  assert.equal(result.diagnostics.normalizedPath, "accountants/7/set-agencies");
  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/accountants/7/set-agencies/");
});

test("backend proxy resolver accepts exactly the four supported accountant action posts", async () => {
  for (const action of ["set-agencies", "reset-password", "activate", "deactivate"]) {
    const { result, calls } = await resolveProxy({ segments: ["accountants", "42", action] });
    assert.equal(result.status, 200);
    assert.equal(calls[0].url, `http://127.0.0.1:8000/api/accountants/42/${action}/`);
  }
});

test("backend proxy resolver rejects unsupported accountant action shapes and methods", async () => {
  for (const method of ["GET", "DELETE"]) {
    const { result, calls } = await resolveProxy({ method, segments: ["accountants", "7", "set-agencies"] });
    assert.equal(result.status, 404);
    assert.deepEqual(result.payload, { detail: "API path is not allowed." });
    assert.equal(calls.length, 0);
  }

  for (const segments of [
    ["accountants", "7", "unknown-action"],
    ["accountants", "abc", "set-agencies"],
    ["accountants", "7", "set_agencies"],
  ]) {
    const { result, calls } = await resolveProxy({ segments });
    assert.equal(result.status, 404);
    assert.deepEqual(result.payload, { detail: "API path is not allowed." });
    assert.equal(calls.length, 0);
  }
});

test("backend proxy resolver keeps csrf enforcement before forwarding unsafe requests", async () => {
  const { result, calls } = await resolveProxy({
    segments: ["accountants", "7", "set-agencies"],
    validateCsrf: csrfFail,
  });

  assert.equal(result.status, 403);
  assert.deepEqual(result.payload, { detail: "Invalid security token." });
  assert.equal(result.diagnostics.allowed, true);
  assert.equal(calls.length, 0);
});

test("backend proxy resolver preserves backend success response status and body", async () => {
  const { result } = await resolveProxy({
    segments: ["accountants", "7", "activate"],
    backendStatus: 202,
    backendPayload: { id: 7, is_active: true },
  });

  assert.equal(result.status, 202);
  assert.deepEqual(result.payload, { id: 7, is_active: true });
});

function jsonResponse(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function mockClientFetch(responses) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    const response = responses[calls.length - 1];
    if (!response) {
      throw new Error(`Unexpected fetch call ${calls.length} to ${url}`);
    }
    return response;
  };
  return { calls, fetchImpl };
}

test("client backend request refreshes once on expired access and retries successfully", async () => {
  resetClientApiStateForTests();
  const { calls, fetchImpl } = mockClientFetch([
    jsonResponse({ csrfToken: "csrf-token" }),
    jsonResponse({ detail: "Access token expired." }, 401),
    jsonResponse({ detail: "Session refreshed." }, 200, { "set-cookie": "tl_access=rotated; HttpOnly" }),
    jsonResponse({ ok: true }),
  ]);

  const payload = await clientRequest("/api/backend/accountants/2/", { method: "PATCH", body: JSON.stringify({ full_name: "Ada" }) }, fetchImpl);

  assert.deepEqual(payload, { ok: true });
  assert.deepEqual(calls.map((call) => call.url), ["/api/auth/csrf", "/api/backend/accountants/2/", "/api/auth/refresh", "/api/backend/accountants/2/"]);
  assert.equal(calls.filter((call) => call.url === "/api/auth/refresh").length, 1);
  assert.equal(calls[1].options.headers["x-csrf-token"], "csrf-token");
  assert.equal(calls[3].options.headers["x-csrf-token"], "csrf-token");
});

test("client PATCH and POST bodies survive refresh retry", async () => {
  for (const { method, path, body } of [
    { method: "PATCH", path: "/api/backend/accountants/2/", body: JSON.stringify({ full_name: "Ada" }) },
    { method: "POST", path: "/api/backend/accountants/2/set-agencies/", body: JSON.stringify({ agency_assignments: selectedAgencyAssignments() }) },
  ]) {
    resetClientApiStateForTests();
    const { calls, fetchImpl } = mockClientFetch([
      jsonResponse({ csrfToken: "csrf-token" }),
      jsonResponse({ detail: "Access token expired." }, 401),
      jsonResponse({ detail: "Session refreshed." }),
      jsonResponse({ ok: true }),
    ]);

    await clientRequest(path, { method, body }, fetchImpl);

    assert.equal(calls[1].options.body, body);
    assert.equal(calls[3].options.body, body);
    assert.equal(calls[1].options.method, method);
    assert.equal(calls[3].options.method, method);
  }
});

test("client multipart import upload survives refresh retry without JSON content type", async () => {
  resetClientApiStateForTests();
  const form = new FormData();
  form.set("agency", "1");
  form.set("transaction_date", "2026-08-27");
  form.set("file", new Blob(["xlsx"], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), "daily.xlsx");
  const { calls, fetchImpl } = mockClientFetch([
    jsonResponse({ csrfToken: "csrf-token" }),
    jsonResponse({ detail: "Access token expired." }, 401),
    jsonResponse({ detail: "Session refreshed." }),
    jsonResponse({ id: 10 }),
  ]);

  await clientRequest("/api/backend/daily-sheet-imports/preview/", { method: "POST", body: form }, fetchImpl);

  assert.equal(calls[1].options.body, form);
  assert.equal(calls[3].options.body, form);
  assert.equal(calls[1].options.headers["x-csrf-token"], "csrf-token");
  assert.equal(calls[3].options.headers["Content-Type"], undefined);
  assert.equal(calls[3].options.headers.Authorization, undefined);
});

test("client refresh retry relies on rotated http-only cookies without exposing tokens", async () => {
  resetClientApiStateForTests();
  const { calls, fetchImpl } = mockClientFetch([
    jsonResponse({ csrfToken: "csrf-token" }),
    jsonResponse({ detail: "Access token expired." }, 401),
    jsonResponse({ detail: "Session refreshed." }, 200, { "set-cookie": "tl_access=rotated; HttpOnly, tl_refresh=rotated-refresh; HttpOnly" }),
    jsonResponse({ ok: true }),
  ]);

  await clientRequest("/api/backend/accountants/2/", { method: "PATCH", body: "{}" }, fetchImpl);

  assert.equal(calls[2].url, "/api/auth/refresh");
  assert.equal(calls[3].url, "/api/backend/accountants/2/");
  assert.equal("Authorization" in calls[3].options.headers, false);
  assert.equal("tl_access" in calls[3].options.headers, false);
  assert.equal("tl_refresh" in calls[3].options.headers, false);
});

test("client invalid refresh does not repeat retries and returns session expired", async () => {
  resetClientApiStateForTests();
  const { calls, fetchImpl } = mockClientFetch([
    jsonResponse({ csrfToken: "csrf-token" }),
    jsonResponse({ detail: "Access token expired." }, 401),
    jsonResponse({ detail: "Session expired." }, 401),
  ]);
  const redirects = [];
  globalThis.window = {
    location: {
      pathname: "/dashboard/accountants/2",
      replace: (path) => redirects.push(path),
    },
  };

  try {
    await assert.rejects(
      clientRequest("/api/backend/accountants/2/", { method: "PATCH", body: "{}" }, fetchImpl),
      (error) => {
        assert.equal(error.status, 401);
        assert.deepEqual(error.payload, { detail: "Session expired." });
        return true;
      },
    );
  } finally {
    delete globalThis.window;
  }

  assert.deepEqual(calls.map((call) => call.url), ["/api/auth/csrf", "/api/backend/accountants/2/", "/api/auth/refresh"]);
  assert.deepEqual(redirects, ["/login"]);
});

test("client non-401 backend errors preserve payload and are not retried", async () => {
  resetClientApiStateForTests();
  const { calls, fetchImpl } = mockClientFetch([
    jsonResponse({ csrfToken: "csrf-token" }),
    jsonResponse({ email: ["Already exists."] }, 400),
  ]);

  await assert.rejects(
    clientRequest("/api/backend/accountants/2/", { method: "PATCH", body: "{}" }, fetchImpl),
    (error) => {
      assert.equal(error.status, 400);
      assert.deepEqual(error.payload, { email: ["Already exists."] });
      return true;
    },
  );

  assert.deepEqual(calls.map((call) => call.url), ["/api/auth/csrf", "/api/backend/accountants/2/"]);
});

test("concurrent expired backend requests share one refresh", async () => {
  resetClientApiStateForTests();
  let refreshResolve;
  const refreshDone = new Promise((resolve) => {
    refreshResolve = resolve;
  });
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/api/auth/csrf") {
      return jsonResponse({ csrfToken: "csrf-token" });
    }
    if (url === "/api/auth/refresh") {
      await refreshDone;
      return jsonResponse({ detail: "Session refreshed." });
    }
    if (calls.filter((call) => call.url === url).length === 1) {
      return jsonResponse({ detail: "Access token expired." }, 401);
    }
    return jsonResponse({ ok: url });
  };

  const first = clientRequest("/api/backend/accountants/2/", { method: "PATCH", body: "{}" }, fetchImpl);
  const second = clientRequest("/api/backend/accountants/2/set-agencies/", { method: "POST", body: "{}" }, fetchImpl);
  await Promise.resolve();
  refreshResolve();
  await Promise.all([first, second]);

  assert.equal(calls.filter((call) => call.url === "/api/auth/refresh").length, 1);
});

test("accountant proxy allowlist only permits supported action methods", () => {
  assert.equal(isAllowedBackendProxyPath("accountants/7/set-agencies", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("accountants/7/reset-password", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("accountants/7/activate", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("accountants/7/deactivate", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("accountants/7/set_agencies", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("accountants/7/set-agencies", "GET"), false);
  assert.equal(isAllowedBackendProxyPath("accountants/7/reset-password", "GET"), false);
  assert.equal(isAllowedBackendProxyPath("accountants/7/unknown-action", "POST"), false);
});

test("phase 4 proxy allowlist permits exact operations and methods only", () => {
  assert.equal(isAllowedBackendProxyPath("people", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("people", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("people/4", "PATCH"), true);
  assert.equal(isAllowedBackendProxyPath("people/4", "DELETE"), true);
  assert.equal(isAllowedBackendProxyPath("tpm-codes/4", "PATCH"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/summary", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/submit", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/approve", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/return", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/reopen", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("tpm-daily-transactions", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("omitted-terminals/6", "DELETE"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/approve", "GET"), false);
  assert.equal(isAllowedBackendProxyPath("daily-sheets/9/mystery", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("anything", "GET"), false);
});

test("phase 5 report proxy allowlist permits exact get-only report paths", () => {
  assert.equal(isAllowedBackendProxyPath("reports/agency-summary", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("reports/agency-summary/export", "GET"), true);
  assert.equal(isBinaryBackendProxyPath("reports/agency-summary/export", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("reports/agency-summary", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("reports/agency-summary/export", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("reports/agency-summary/delete", "GET"), false);
  assert.equal(isAllowedBackendProxyPath("reports/anything", "GET"), false);
});

test("weekly schedule proxy allowlist permits exact paths and methods only", () => {
  assert.equal(isAllowedBackendProxyPath("games", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules/7", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules/7", "PATCH"), true);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules/7", "DELETE"), true);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules", "DELETE"), false);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules/abc", "PATCH"), false);
  assert.equal(isAllowedBackendProxyPath("weekly-game-schedules/7/activate", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("games", "POST"), false);
});

test("weekly schedule proxy keeps csrf enforcement before unsafe forwarding", async () => {
  const { result, calls } = await resolveProxy({
    segments: ["weekly-game-schedules"],
    body: JSON.stringify({ game: 1, weekday: 1 }),
    validateCsrf: csrfFail,
  });

  assert.equal(result.status, 403);
  assert.deepEqual(result.payload, { detail: "Invalid security token." });
  assert.equal(result.diagnostics.allowed, true);
  assert.equal(calls.length, 0);
});

test("daily sheet import proxy allowlist permits exact paths and methods only", () => {
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/preview", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/12", "GET"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/12/confirm", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/12/cancel", "POST"), true);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/preview", "GET"), false);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/12/confirm", "GET"), false);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/12/delete", "POST"), false);
  assert.equal(isAllowedBackendProxyPath("daily-sheet-imports/abc/confirm", "POST"), false);
});

test("daily sheet import proxy preserves csrf and multipart request body", async () => {
  const form = new FormData();
  form.set("agency", "1");
  form.set("transaction_date", "2026-08-27");
  form.set("file", new Blob(["xlsx"]), "daily.xlsx");
  const request = new Request("http://localhost/api/backend/daily-sheet-imports/preview/", {
    method: "POST",
    body: form,
    headers: { "x-csrf-token": "csrf-token" },
  });
  const calls = [];

  const result = await resolveBackendProxyRequest(
    request,
    { params: Promise.resolve({ path: ["daily-sheet-imports", "preview"] }) },
    {
      cookieStore: cookieStore(),
      validateCsrf: csrfPass,
      backendRequest: async (backendPath, options) => {
        calls.push({ backendPath, options });
        return { status: 201, payload: { id: 12 } };
      },
    },
  );

  assert.equal(result.status, 201);
  assert.equal(calls[0].backendPath, "/daily-sheet-imports/preview");
  assert.equal(calls[0].options.method, "POST");
  assert.ok(calls[0].options.body instanceof FormData);

  const blocked = await resolveProxy({
    segments: ["daily-sheet-imports", "12", "confirm"],
    body: JSON.stringify({ replace_existing: true }),
    validateCsrf: csrfFail,
  });
  assert.equal(blocked.result.status, 403);
  assert.equal(blocked.calls.length, 0);
});

test("daily sheet import screen validates gates and avoids browser storage", async () => {
  const source = await file("components/DailySheetImportClient.js");
  const page = await file("app/dashboard/daily-sheets/import/page.js");
  const dailySheets = await file("components/DailySheetsClient.js");
  const css = await file("app/globals.css");

  assert.match(dailySheets, /Upload Excel/);
  assert.match(page, /DailySheetImportClient/);
  assert.match(source, /Choose a \.xlsx file no larger than 5 MB\./);
  assert.match(source, /requires_date_mismatch_ack/);
  assert.match(source, /replaceExisting/);
  assert.match(source, /Confirm Import/);
  assert.match(source, /router\.push\(`\/dashboard\/daily-sheets\/\$\{payload\.daily_sheet\}`\)/);
  assert.match(source, /previewPayload\.game_columns/);
  assert.match(source, /batch\.errors\?\.length/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|Authorization|tl_access|tl_refresh/);
  assert.match(css, /\.import-preview-wrap\s*\{[^}]*overflow-x:\s*auto;/s);
  assert.match(css, /@media \(max-width: 680px\)[\s\S]*\.metric-grid,\s*\n\s*\.field-grid/s);
});

test("weekly schedule Timed and Whole Day form validation is deterministic", () => {
  const blank = emptyScheduleForm();
  assert.equal(validateScheduleForm(blank), "Select a game.");
  const timed = { ...blank, game: "4", weekday: "1", display_order: "1", closing_time: "12:30", draw_time: "12:45" };
  assert.equal(validateScheduleForm(timed), "");
  assert.deepEqual(schedulePayload(timed), {
    game: 4,
    weekday: 1,
    display_order: 1,
    is_whole_day: false,
    closing_time: "12:30",
    draw_time: "12:45",
    is_active: true,
  });
  assert.equal(validateScheduleForm({ ...timed, draw_time: "" }), "Timed schedules require both Closing Time and Draw Time.");
  assert.equal(validateScheduleForm({ ...timed, draw_time: "12:00" }), "Draw Time must be later than Closing Time.");
});

test("weekly schedule Whole Day mode clears time fields", () => {
  const form = { ...emptyScheduleForm(), game: "4", closing_time: "12:30", draw_time: "12:45" };
  const wholeDay = withScheduleMode(form, true);

  assert.equal(wholeDay.closing_time, "");
  assert.equal(wholeDay.draw_time, "");
  assert.equal(validateScheduleForm({ ...wholeDay, weekday: "1", display_order: "1" }), "");
  assert.equal(schedulePayload({ ...wholeDay, weekday: "1", display_order: "1" }).closing_time, null);
});

test("weekly schedule screen hides mutation controls from accountants and keeps responsive layout", async () => {
  const component = await file("components/GameScheduleClient.js");
  const css = await file("app/globals.css");

  assert.match(component, /canMutate = user\.role === "SUPER_ADMIN"/);
  assert.match(component, /canMutate \? \(/);
  assert.match(component, /Timed/);
  assert.match(component, /Whole Day/);
  assert.match(component, /window\.confirm/);
  assert.match(component, /weekly-game-schedules/);
  assert.match(css, /\.schedule-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) minmax\(300px, 360px\);[^}]*max-width:\s*100%;/s);
  assert.match(css, /@media \(max-width: 980px\)[\s\S]*\.schedule-layout\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\);/);
});

test("phase 4 people parsing and search handles names and tpm codes", () => {
  const people = [
    { id: 1, full_name: "Ayo", agency: 1, agency_name: "Musa 1", tpm_codes: [{ id: 4, code: "TPM-A", is_active: true }] },
    { id: 2, full_name: "Bisi", agency: 2, agency_name: "Sango", tpm_codes: [{ id: 5, code: "SUB-A", is_active: true }] },
  ];
  assert.deepEqual(listFromPayload({ results: people }), people);
  assert.equal(searchPeople(people, "ayo").length, 1);
  assert.equal(searchPeople(people, "sub-a")[0].full_name, "Bisi");
});

test("phase 4 role and agency visibility uses assigned agencies", () => {
  const user = { role: "ACCOUNTANT", agency_assignments: [{ agency: { id: 2 }, can_create: true, can_edit: false }] };
  const rows = [{ id: 1, agency: 1 }, { id: 2, agency: 2 }];
  assert.deepEqual(filterByVisibleAgency(rows, user).map((row) => row.id), [2]);
  assert.equal(actionAvailability(user, { agency: 2, status: "DRAFT" }).canSubmit, false);
});

test("phase 4 transaction payload and previews are deterministic", () => {
  const games = [{ id: 10 }, { id: 11 }];
  const payload = buildTransactionPayload(7, 4, games, { 10: "100.005", 11: "50" });
  assert.deepEqual(payload, {
    daily_sheet: 7,
    tpm_code: 4,
    sales: [
      { daily_sheet_game: 10, amount: "100.00" },
      { daily_sheet_game: 11, amount: "50.00" },
    ],
  });
  const preview = calculateTransactionPreview({ 10: "100", 11: "50" }, true);
  assert.equal(preview.netSales, 150);
  assert.equal(preview.toPay, 142.5);
  assert.equal(preview.subagentShare, 3);
  assert.equal(preview.organisationShare, 4.5);
});

test("phase 4 multiple tpm codes for one person become separate selectable terminals", () => {
  const options = activeTpmOptions([{ id: 1, full_name: "Ayo", agency: 1, agent_type: "MAIN_AGENT", tpm_codes: [{ id: 3, code: "A" }, { id: 4, code: "B", is_active: true }] }]);
  assert.deepEqual(options.map((item) => item.code), ["A", "B"]);
});

test("phase 4 manual tax and difference display stay separate from to pay", () => {
  assert.equal(differenceLabel(5), "Positive difference");
  assert.equal(differenceLabel(0), "Zero difference");
  assert.equal(differenceLabel(-5), "Negative difference");
  const preview = calculateTransactionPreview({ a: "200" }, false);
  assert.equal(preview.toPay, 190);
});

test("phase 4 screens include loading empty error workflow and unsaved-change states", async () => {
  const sources = await Promise.all([
    file("components/PeopleTpmClient.js"),
    file("components/DailySheetsClient.js"),
    file("components/DailySheetDetailClient.js"),
  ]);
  const source = sources.join("\n");
  assert.match(source, /Loading people|Loading daily sheets/);
  assert.match(source, /No people match|No daily sheets match|No transactions entered/);
  assert.match(source, /form-error|form-success/);
  assert.match(source, /beforeunload/);
  assert.match(source, /canApprove|canReturn|canReopen/);
});

test("phase 5 report query construction and period display are deterministic", () => {
  const daily = { agency: "1", period: "daily", date: "2026-08-24", statuses: ["APPROVED"] };
  assert.equal(buildReportQuery(daily), "agency=1&period=daily&date=2026-08-24&status=APPROVED");
  assert.deepEqual(resolvePeriodDisplay({ ...daily, period: "weekly", date: "2026-08-27" }), { start: "2026-08-24", end: "2026-08-30" });
  assert.deepEqual(resolvePeriodDisplay({ ...daily, period: "monthly", month: "02", year: "2024" }), { start: "2024-02-01", end: "2024-02-29" });
  assert.equal(validateReportFilters({ ...daily, period: "custom", startDate: "2026-08-31", endDate: "2026-08-24" }), "Custom start date must be on or before end date.");
  assert.equal(filenameFromDisposition('attachment; filename="treasureland-musa-1.xlsx"'), "treasureland-musa-1.xlsx");
});

test("phase 5 reports page includes required states dynamic tables and no browser storage", async () => {
  const source = [
    await file("components/ReportsClient.js"),
    await file("app/dashboard/reports/page.js"),
    await file("components/DashboardShell.js"),
  ].join("\n");
  assert.match(source, /role !== "SUPER_ADMIN"/);
  assert.match(source, /AccessDenied/);
  assert.match(source, /Generate report/);
  assert.match(source, /Download Excel/);
  assert.match(source, /Operational\/non-final report/);
  assert.match(source, /Loading report/);
  assert.match(source, /No daily sheets match this report/);
  assert.match(source, /form-error/);
  assert.match(source, /report\.game_columns\.map/);
  assert.match(source, /difference-/);
  assert.match(source, /summary-table-wrap/);
  assert.doesNotMatch(source, /localStorage|sessionStorage/);
  assert.doesNotMatch(source, /can_export \? \[\{ label: "Reports"/);
});

test("phase 5 client download preserves binary headers and refresh retry", async () => {
  resetClientApiStateForTests();
  const body = new Blob(["xlsx"], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  const { calls, fetchImpl } = mockClientFetch([
    jsonResponse({ detail: "Access token expired." }, 401),
    jsonResponse({ detail: "Session refreshed." }),
    new Response(body, {
      status: 200,
      headers: {
        "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content-disposition": 'attachment; filename="treasureland-report.xlsx"',
      },
    }),
  ]);
  const result = await clientDownload("/api/backend/reports/agency-summary/export/?agency=1&period=daily&date=2026-08-24", {}, fetchImpl);
  assert.equal(calls.filter((call) => call.url === "/api/auth/refresh").length, 1);
  assert.equal(result.contentType, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  assert.equal(result.contentDisposition, 'attachment; filename="treasureland-report.xlsx"');
  assert.equal(await result.blob.text(), "xlsx");
});

test("phase 5 backend proxy marks report export as binary and preserves error status path", async () => {
  const { result, calls } = await resolveProxy({
    method: "GET",
    segments: ["reports", "agency-summary", "export"],
    path: "/api/backend/reports/agency-summary/export/?agency=1&period=daily&date=2026-08-24",
    backendPayload: { detail: "Forbidden" },
    backendStatus: 403,
  });
  assert.equal(result.status, 403);
  assert.equal(calls[0].options.binary, true);
  assert.equal(calls[0].backendPath, "/reports/agency-summary/export?agency=1&period=daily&date=2026-08-24");
});

test("phase 4 daily sheet summary keeps horizontal overflow inside the table wrapper", async () => {
  const component = await file("components/DailySheetDetailClient.js");
  const css = await file("app/globals.css");

  assert.match(component, /className="table-wrap summary-table-wrap"/);
  assert.match(component, /tabIndex="0"/);
  assert.match(component, /aria-label="Daily Sheet Summary table with horizontal scrolling"/);
  assert.match(component, /className="summary-table"/);
  assert.match(component, /520 \+ sheet\.sheet_games\.length \* 132/);

  assert.match(css, /\.dashboard-frame\s*\{[^}]*max-width:\s*100vw;[^}]*min-width:\s*0;[^}]*grid-template-columns:\s*280px minmax\(0, 1fr\);/s);
  assert.match(css, /\.dashboard-main\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(css, /\.dashboard-content\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(css, /\.page-stack\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(css, /\.panel\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(css, /\.content-grid,\s*\n\.form-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1\.35fr\) minmax\(320px, 0\.65fr\);[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(css, /\.table-wrap\s*\{[^}]*max-width:\s*100%;[^}]*min-width:\s*0;[^}]*overflow-x:\s*auto;[^}]*overscroll-behavior-inline:\s*contain;/s);
  assert.match(css, /\.summary-table\s*\{[^}]*width:\s*max-content;/s);
  assert.match(css, /\.summary-table th\s*\{[^}]*overflow-wrap:\s*anywhere;/s);
  assert.match(css, /\.responsive-table:not\(\.summary-table-wrap\) table/);
  assert.match(css, /\.scroll-hint/);
  assert.doesNotMatch(css, /zoom\s*:/);
  assert.doesNotMatch(css, /transform\s*:\s*scale/);
});

test("mocked outgoing backend requests use normalized urls and preserve bodies", async () => {
  const calls = [];
  const mockFetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await backendRequestWithFetch("accountants", { method: "GET" }, mockFetch);
  await backendRequestWithFetch("accountants/4/activate", { method: "POST", body: JSON.stringify({}) }, mockFetch);
  await backendRequestWithFetch("accountants/4/deactivate?reason=test", { method: "POST", body: "{}", headers: { Authorization: "Bearer test" } }, mockFetch);

  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/accountants/");
  assert.equal(calls[1].url, "http://127.0.0.1:8000/api/accountants/4/activate/");
  assert.equal(calls[1].options.body, "{}");
  assert.equal(calls[2].url, "http://127.0.0.1:8000/api/accountants/4/deactivate/?reason=test");
  assert.equal(calls[2].options.headers.Authorization, "Bearer test");
});

test("unexpected upstream html errors are sanitized while validation payloads survive", async () => {
  await assert.rejects(
    backendRequestWithFetch("accountants", {}, async () => new Response("<html>debug traceback</html>", { status: 500, headers: { "content-type": "text/html" } })),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 500);
      assert.equal(error.exposePayload, false);
      assert.equal(error.payload.detail, "Upstream service error.");
      return true;
    },
  );

  await assert.rejects(
    backendRequestWithFetch("accountants", {}, async () => new Response(JSON.stringify({ email: ["Already exists."] }), { status: 400, headers: { "content-type": "application/json" } })),
    (error) => {
      assert.equal(error.status, 400);
      assert.equal(error.exposePayload, true);
      assert.deepEqual(error.payload, { email: ["Already exists."] });
      return true;
    },
  );
});

test("api list parsing supports plain arrays and paginated results", () => {
  const agencies = [
    { id: 1, name: "Musa 1", code: "musa-1" },
    { id: 2, name: "Omolade", code: "omolade" },
  ];
  assert.deepEqual(listFromApiPayload(agencies), agencies);
  assert.deepEqual(listFromApiPayload({ results: agencies }), agencies);
  assert.deepEqual(activeAgenciesFromPayload(agencies).map((agency) => agency.name), ["Musa 1", "Omolade"]);
  assert.deepEqual(activeAgenciesFromPayload([{ id: 3, name: "Inactive", is_active: false }]), []);
});

test("assignment rows show all active agencies when accountant has no assignments", () => {
  const agencies = [
    { id: 1, name: "Musa 1" },
    { id: 3, name: "Omolade" },
  ];
  const rows = buildAssignmentRows({ agency_assignments: [] }, agencies);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((row) => row.agency_name), ["Musa 1", "Omolade"]);
  assert.deepEqual(rows.map((row) => row.selected), [false, false]);
});

test("existing assignments are preselected with independent permission flags", () => {
  const accountant = {
    agency_assignments: [
      { agency: { id: 1, name: "Musa 1" }, can_create: true, can_edit: false, can_delete: false, can_export: true, can_view_history: false },
      { agency: { id: 3, name: "Omolade" }, can_create: false, can_edit: true, can_delete: true, can_export: false, can_view_history: true },
    ],
  };
  const rows = buildAssignmentRows(accountant, [
    { id: 1, name: "Musa 1" },
    { id: 3, name: "Omolade" },
  ]);
  assert.equal(rows[0].selected, true);
  assert.equal(rows[0].can_create, true);
  assert.equal(rows[0].can_edit, false);
  assert.equal(rows[1].selected, true);
  assert.equal(rows[1].can_create, false);
  assert.equal(rows[1].can_edit, true);
  assert.equal(rows[1].can_delete, true);
});

test("failed agency loading does not trigger assignment replacement on edit", () => {
  assert.equal(shouldSyncAgencyAssignments(true, ""), true);
  assert.equal(shouldSyncAgencyAssignments(true, "Unable to load active agencies."), false);
  assert.equal(shouldSyncAgencyAssignments(false, ""), false);
});

test("accountant form reports partial save instead of complete success on assignment failure", async () => {
  const source = await file("components/AccountantForm.js");
  assert.match(source, /Profile saved, but agency permissions were not saved/);
  assert.match(source, /Your selections are still here/);
});

function selectedAgencyAssignments() {
  return [
    { agency: 1, can_create: true, can_edit: false, can_delete: false, can_export: true, can_view_history: false },
    { agency: 3, can_create: false, can_edit: true, can_delete: true, can_export: false, can_view_history: true },
  ];
}

function profileInput() {
  return { fullName: "Ada Accountant", email: "ada@example.com", password: "StrongPass123!", isActive: true };
}

async function submitWithMockedRequests(options, responses) {
  const calls = [];
  const result = await saveAccountantWithAssignments({
    profile: profileInput(),
    selectedAssignments: selectedAgencyAssignments(),
    agencyLoadError: "",
    request: async (path, requestOptions) => {
      calls.push({ path, options: requestOptions, body: requestOptions.body ? JSON.parse(requestOptions.body) : null });
      return responses[calls.length - 1];
    },
    ...options,
  });
  return { result, calls };
}

test("edit accountant uses original id for profile patch and assignment save", async () => {
  const { result, calls } = await submitWithMockedRequests(
    { editing: true, accountant: { id: 2 } },
    [{ email: "ada@example.com", full_name: "Ada Accountant", is_active: true }, { id: 2 }],
  );

  assert.equal(result.ok, true);
  assert.equal(result.accountantId, "2");
  assert.equal(calls[0].path, "/api/backend/accountants/2/");
  assert.equal(calls[0].options.method, "PATCH");
  assert.equal(calls[1].path, "/api/backend/accountants/2/set-agencies/");
  assert.equal(calls[1].options.method, "POST");
});

test("edit accountant response without id still uses original id", async () => {
  const { result, calls } = await submitWithMockedRequests(
    { editing: true, accountant: { id: 2 } },
    [{ email: "ada@example.com", full_name: "Ada Accountant", is_active: true }, { id: 2 }],
  );

  assert.equal(result.accountantId, "2");
  assert.equal(calls[1].path, "/api/backend/accountants/2/set-agencies/");
});

test("create accountant uses returned numeric id", async () => {
  const { result, calls } = await submitWithMockedRequests({ editing: false, accountant: null }, [{ id: 9, email: "ada@example.com" }]);

  assert.equal(result.ok, true);
  assert.equal(result.accountantId, "9");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/backend/accountants/");
  assert.equal(calls[0].options.method, "POST");
});

test("missing or invalid accountant ids prevent assignment requests", async () => {
  for (const accountant of [{}, { id: undefined }, { id: null }, { id: Number.NaN }, { id: "abc" }, { id: 0 }]) {
    const { result, calls } = await submitWithMockedRequests({ editing: true, accountant }, []);
    assert.equal(result.ok, false);
    assert.equal(result.internalError, ACCOUNTANT_ID_ERROR);
    assert.equal(calls.length, 0);
  }

  const createdWithoutId = await submitWithMockedRequests({ editing: false, accountant: null }, [{ email: "ada@example.com" }]);
  assert.equal(createdWithoutId.result.ok, false);
  assert.equal(createdWithoutId.result.internalError, ACCOUNTANT_ID_ERROR);
  assert.equal(createdWithoutId.calls.length, 1);
});

test("accountant submit flow never generates undefined, null, NaN or nonnumeric id paths", async () => {
  const cases = [
    submitWithMockedRequests({ editing: true, accountant: { id: 2 } }, [{}, {}]),
    submitWithMockedRequests({ editing: false, accountant: null }, [{ id: 9 }]),
    submitWithMockedRequests({ editing: true, accountant: { id: "abc" } }, []),
    submitWithMockedRequests({ editing: false, accountant: null }, [{ id: "abc" }]),
  ];
  const results = await Promise.all(cases);
  const generatedPaths = results.flatMap(({ calls }) => calls.map((call) => call.path));

  assert.equal(generatedPaths.some((path) => /undefined|null|NaN|accountants\/abc/.test(path)), false);
});

test("assignment payload preserves independent Musa 1 and Omolade permissions", async () => {
  const { calls } = await submitWithMockedRequests({ editing: true, accountant: { id: 2 } }, [{}, {}]);
  const payload = calls[1].body.agency_assignments;

  assert.deepEqual(payload, selectedAgencyAssignments());
  assert.deepEqual(payload[0], { agency: 1, can_create: true, can_edit: false, can_delete: false, can_export: true, can_view_history: false });
  assert.deepEqual(payload[1], { agency: 3, can_create: false, can_edit: true, can_delete: true, can_export: false, can_view_history: true });
});
