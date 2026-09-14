"use client";

import { UPLOAD_SERVICE_ERROR } from "./request-errors.js";

export function validationMessage(payload, status) {
  if (status >= 500) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    if (detail === UPLOAD_SERVICE_ERROR) return UPLOAD_SERVICE_ERROR;
    if (detail && !/traceback|password|token|cookie|secret|database url/i.test(detail)) return detail;
    return "Upstream service error.";
  }
  function messages(value) {
    if (typeof value === "string") return [value];
    if (Array.isArray(value)) return value.flatMap(messages);
    if (value && typeof value === "object") return Object.values(value).flatMap(messages);
    return [];
  }
  return messages(payload?.detail || payload).join(" ") || "Request failed.";
}

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
    return { detail: "Unexpected server response." };
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
  const multipart = typeof FormData !== "undefined" && options.body instanceof FormData;
  const supplied = new Headers(options.headers || {});
  if (multipart) {
    // Each browser attempt serializes the reusable FormData with a fresh boundary.
    supplied.delete("content-type");
    supplied.delete("content-length");
  }
  try {
    return await fetchImpl(path, {
      ...options,
      method,
      headers: {
        Accept: "application/json",
        ...(options.body && !multipart ? { "Content-Type": "application/json" } : {}),
        ...Object.fromEntries(supplied),
        ...csrfHeader,
      },
    });
  } catch (error) {
    if (multipart) throw new ClientApiError(UPLOAD_SERVICE_ERROR, 504, { detail: UPLOAD_SERVICE_ERROR });
    throw error;
  }
}

async function sendDownloadRequest(fetchImpl, path, options, method, csrfHeader) {
  return fetchImpl(path, {
    ...options,
    method,
    headers: {
      Accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/json",
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
    const uploadFailure = options.body instanceof FormData && response.status >= 500;
    throw new ClientApiError(uploadFailure ? UPLOAD_SERVICE_ERROR : validationMessage(payload, response.status), response.status, payload);
  }
  return payload;
}

export async function clientDownload(path, options = {}, fetchImpl = fetch) {
  const method = (options.method || "GET").toUpperCase();
  const csrfHeader = ["GET", "HEAD", "OPTIONS"].includes(method) ? {} : { "x-csrf-token": await getCsrfToken(fetchImpl) };
  let response = await sendDownloadRequest(fetchImpl, path, options, method, csrfHeader);

  if (response.status === 401 && canRefreshRequest(path)) {
    try {
      await refreshSession(fetchImpl, csrfHeader);
    } catch {
      redirectToLogin();
      throw new ClientApiError("Session expired. Please sign in again.", 401, { detail: "Session expired." });
    }
    response = await sendDownloadRequest(fetchImpl, path, options, method, csrfHeader);
  }

  if (!response.ok) {
    const payload = await parse(response);
    throw new ClientApiError(validationMessage(payload, response.status), response.status, payload);
  }
  const blob = await response.blob();
  return {
    blob,
    contentType: response.headers.get("content-type") || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    contentDisposition: response.headers.get("content-disposition") || "",
  };
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
