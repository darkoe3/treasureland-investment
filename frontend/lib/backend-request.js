import { buildBackendUrl } from "./backend-url.js";
import { PROXY_SERVICE_ERROR } from "./request-errors.js";

export class ApiError extends Error {
  constructor(message, status, payload = null, exposePayload = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.exposePayload = exposePayload;
  }
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  if (!text) {
    return null;
  }
  if (!contentType.includes("application/json")) {
    return { detail: "Unexpected upstream response." };
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: "Unexpected upstream response." };
  }
}

function requestHeaders(options) {
  const supplied = new Headers(options.headers || {});
  const headers = { Accept: supplied.get("accept") || options.accept || "application/json" };
  // Only server-owned authorization and representation headers are forwarded.
  if (supplied.has("authorization")) headers.Authorization = supplied.get("authorization");
  const form = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!form && supplied.has("content-type")) headers["Content-Type"] = supplied.get("content-type");
  else if (!form && options.body) headers["Content-Type"] = "application/json";
  return headers;
}

function transportError(error) {
  if (error instanceof ApiError) return error;
  const wrapped = new ApiError(PROXY_SERVICE_ERROR, 504);
  wrapped.transportFailure = true;
  wrapped.cause = error;
  return wrapped;
}

function safeErrorPayload(payload) {
  return payload && typeof payload === "object" && typeof payload.detail === "string" && payload.detail !== "Unexpected upstream response." && !/traceback|password|token|cookie|secret|database url/i.test(payload.detail)
    ? payload
    : { detail: "Upstream service error." };
}

export async function backendRequestWithFetchResponse(path, options = {}, fetchImpl = fetch, timeoutMs = 10000) {
  const { timeoutMs: requestTimeoutMs = timeoutMs, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await fetchImpl(buildBackendUrl(path), {
      ...fetchOptions,
      cache: "no-store",
      signal: controller.signal,
      headers: requestHeaders(options),
    });
    const payload = await parseResponse(response);
    if (!response.ok) {
      const expectedError = response.status >= 400 && response.status < 500;
      const exposedPayload = expectedError ? payload : safeErrorPayload(payload);
      const message = exposedPayload?.detail || "Request failed.";
      const exposePayload = expectedError || exposedPayload.detail !== "Upstream service error.";
      throw new ApiError(message, response.status, exposedPayload, exposePayload);
    }
    return { status: response.status, payload, contentType: response.headers.get("content-type") };
  } catch (error) {
    throw transportError(error);
  } finally {
    clearTimeout(timeout);
  }
}

export async function backendRequestWithFetch(path, options = {}, fetchImpl = fetch, timeoutMs = 10000) {
  const response = await backendRequestWithFetchResponse(path, options, fetchImpl, timeoutMs);
  return response.payload;
}

export async function backendRawResponseWithFetch(path, options = {}, fetchImpl = fetch, timeoutMs = 30000) {
  const { timeoutMs: requestTimeoutMs = timeoutMs, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    return await fetchImpl(buildBackendUrl(path), {
      ...fetchOptions,
      cache: "no-store",
      signal: controller.signal,
      headers: requestHeaders(options),
    });
  } catch (error) {
    throw transportError(error);
  } finally {
    clearTimeout(timeout);
  }
}
