import { buildBackendUrl } from "./backend-url.js";

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

function hasMultipartBody(body) {
  return typeof FormData !== "undefined" && body instanceof FormData;
}

export async function backendRequestWithFetchResponse(path, options = {}, fetchImpl = fetch, timeoutMs = 10000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(buildBackendUrl(path), {
      ...options,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.body && !hasMultipartBody(options.body) ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const payload = await parseResponse(response);
    if (!response.ok) {
      const expectedError = response.status >= 400 && response.status < 500;
      const message = expectedError ? payload?.detail || "Request failed." : "Upstream service error.";
      throw new ApiError(message, response.status, expectedError ? payload : { detail: "Upstream service error." }, expectedError);
    }
    return { status: response.status, payload };
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError("The server took too long to respond.", 504, { detail: "The server took too long to respond." }, false);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function backendRequestWithFetch(path, options = {}, fetchImpl = fetch, timeoutMs = 10000) {
  const response = await backendRequestWithFetchResponse(path, options, fetchImpl, timeoutMs);
  return response.payload;
}

export async function backendRawResponseWithFetch(path, options = {}, fetchImpl = fetch, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetchImpl(buildBackendUrl(path), {
      ...options,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: options.accept || "*/*",
        ...(options.body && !hasMultipartBody(options.body) ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError("The server took too long to respond.", 504, { detail: "The server took too long to respond." }, false);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
