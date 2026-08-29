"use client";

export class ClientApiError extends Error {
  constructor(message, status, payload = null) {
    super(message);
    this.name = "ClientApiError";
    this.status = status;
    this.payload = payload;
  }
}

let csrfToken = null;
let refreshPromise = null;

async function getCsrfToken(fetchImpl = fetch) {
  if (csrfToken) {
    return csrfToken;
  }
  const response = await fetchImpl("/api/auth/csrf", { cache: "no-store" });
  const payload = await parse(response);
  if (!response.ok || !payload?.csrfToken) {
    throw new ClientApiError("Could not prepare secure request.", response.status, payload);
  }
  csrfToken = payload.csrfToken;
  return csrfToken;
}

async function parse(response) {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function canRefreshRequest(path) {
  const pathname = String(path || "").split("?")[0];
  return pathname.startsWith("/api/backend/");
}

function redirectToLogin() {
  if (typeof window === "undefined" || window.location.pathname === "/login") {
    return;
  }
  window.location.replace("/login");
}

async function refreshSession(fetchImpl, csrfHeader) {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const response = await fetchImpl("/api/auth/refresh", {
        method: "POST",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          ...csrfHeader,
        },
      });
      const payload = await parse(response);
      if (!response.ok) {
        throw new ClientApiError(payload?.detail || "Session expired.", response.status, payload);
      }
      return payload;
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function sendRequest(fetchImpl, path, options, method, csrfHeader) {
  return fetchImpl(path, {
    ...options,
    method,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...csrfHeader,
      ...(options.headers || {}),
    },
  });
}

export async function clientRequest(path, options = {}, fetchImpl = fetch) {
  const method = (options.method || "GET").toUpperCase();
  const csrfHeader = ["GET", "HEAD", "OPTIONS"].includes(method) ? {} : { "x-csrf-token": await getCsrfToken(fetchImpl) };
  let response = await sendRequest(fetchImpl, path, options, method, csrfHeader);
  let payload = await parse(response);

  if (response.status === 401 && canRefreshRequest(path)) {
    try {
      await refreshSession(fetchImpl, csrfHeader);
    } catch {
      redirectToLogin();
      throw new ClientApiError("Session expired. Please sign in again.", 401, { detail: "Session expired." });
    }
    response = await sendRequest(fetchImpl, path, options, method, csrfHeader);
    payload = await parse(response);
  }

  if (!response.ok) {
    throw new ClientApiError(payload?.detail || "Request failed.", response.status, payload);
  }
  return payload;
}

export function resetClientApiStateForTests() {
  csrfToken = null;
  refreshPromise = null;
}

export function apiPath(path) {
  const [rawPath, rawQuery = ""] = String(path || "").split("?");
  const trimmed = rawPath.replace(/^\/+/, "");
  const normalized = trimmed.replace(/\/+$/, "");
  const trailingSlash = normalized && /\/+$/.test(trimmed) ? "/" : "";
  const query = rawQuery ? `?${rawQuery}` : "";
  return `/api/backend/${normalized}${trailingSlash}${query}`;
}
