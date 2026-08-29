import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { buildBackendUrl, normalizeBackendPath } from "../lib/backend-url.js";
import { ApiError, backendRequestWithFetch } from "../lib/backend-request.js";
import { normalizeProxySegments, resolveBackendProxyRequest } from "../lib/backend-proxy.js";
import { ACCOUNTANT_ID_ERROR, saveAccountantWithAssignments } from "../lib/accountant-submit.js";
import { apiPath, clientRequest, resetClientApiStateForTests } from "../lib/client-api.js";
import { backendPathFromProxySegments, isAllowedBackendProxyPath } from "../lib/controlled-proxy-path.js";
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
  assert.match(allowlist, /ALLOWED_PREFIXES/);
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
