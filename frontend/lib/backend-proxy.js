import { ApiError } from "./backend-request.js";
import { PROXY_SERVICE_ERROR, UPLOAD_SERVICE_ERROR } from "./request-errors.js";
import { backendPathFromProxySegments, isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "./controlled-proxy-path.js";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const ERROR_NAMES = new Set(["AbortError", "TimeoutError", "TypeError", "Error", "ApiError", "RangeError"]);
const ERROR_CODES = new Set(["ABORT_ERR", "ECONNREFUSED", "ECONNRESET", "ENOTFOUND", "EAI_AGAIN", "ETIMEDOUT", "EPIPE", "UND_ERR_CONNECT_TIMEOUT", "UND_ERR_HEADERS_TIMEOUT", "UND_ERR_BODY_TIMEOUT", "UND_ERR_REQ_CONTENT_LENGTH_MISMATCH", "UND_ERR_SOCKET", "UND_ERR_INVALID_ARG", "ERR_INVALID_ARG_TYPE", "ERR_INVALID_STATE", "ERR_TLS_CERT_ALTNAME_INVALID", "CERT_HAS_EXPIRED", "DEPTH_ZERO_SELF_SIGNED_CERT"]);

export function normalizeProxySegments(segments = []) {
  const cleanSegments = (Array.isArray(segments) ? segments : [])
    .flatMap((segment) => String(segment || "").split("/"))
    .map((segment) => segment.trim()).filter(Boolean);
  if (cleanSegments[0] === "api" && cleanSegments[1] === "backend") return cleanSegments.slice(2);
  if (cleanSegments[0] === "backend") return cleanSegments.slice(1);
  return cleanSegments;
}

export function proxyDiagnostics({ request, method, normalizedPath = null, allowed = false }) {
  const contentType = request.headers.get("content-type") || "";
  const mediaType = contentType.split(";")[0].trim().toLowerCase();
  return {
    method: ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"].includes(method) ? method : "OTHER",
    normalizedPath: allowed ? normalizedPath : null,
    allowed,
    mediaType: ["multipart/form-data", "application/json", "application/octet-stream", "text/plain"].includes(mediaType) ? mediaType : "other",
    hasMultipartBoundary: /;\s*boundary\s*=\s*(?:"[^"]+"|[^;\s]+)/i.test(contentType),
    bodyPresent: Boolean(request.body),
    bodyByteLength: null,
    errorName: null,
    errorCode: null,
    causeCode: null,
    elapsedMs: 0,
  };
}

export function logProxyDiagnostics(diagnostics, logger = console) {
  // Construct the log explicitly: no URLs, arbitrary exception text or header values.
  const { method, normalizedPath, mediaType, hasMultipartBoundary, bodyPresent, bodyByteLength, errorName, errorCode, causeCode, elapsedMs } = diagnostics;
  const safe = { method, normalizedPath, mediaType, hasMultipartBoundary, bodyPresent, bodyByteLength, errorName, errorCode, causeCode, elapsedMs };
  if (errorName) logger.warn("backend proxy", safe);
  else if (process.env.TL_PROXY_DEBUG === "1") logger.info("backend proxy", safe);
}

export async function resolveBackendProxyRequest(request, context, { cookieStore, validateCsrf, backendRequest, onDiagnostics = () => {} }) {
  const started = performance.now();
  const method = String(request.method || "GET").toUpperCase();
  const diagnostics = proxyDiagnostics({ request, method });
  try {
    const params = await context.params;
    const segments = normalizeProxySegments(params?.path || []);
    const normalizedPath = segments.join("/");
    diagnostics.allowed = isAllowedBackendProxyPath(normalizedPath, method);
    diagnostics.normalizedPath = diagnostics.allowed ? normalizedPath : null;
    if (UNSAFE_METHODS.has(method) && !validateCsrf(request, cookieStore)) {
      return { status: 403, payload: { detail: "Invalid security token." }, diagnostics };
    }
    if (!diagnostics.allowed) return { status: 404, payload: { detail: "API path is not allowed." }, diagnostics };

    const headers = {};
    let body;
    if (method !== "GET" && method !== "HEAD") {
      if (diagnostics.mediaType === "multipart/form-data") {
        if (!diagnostics.hasMultipartBoundary) return { status: 400, payload: { detail: "The multipart upload is missing its boundary." }, diagnostics };
        // Option A: read once, forward the exact bytes and original boundary.
        body = await request.arrayBuffer();
        diagnostics.bodyByteLength = body.byteLength;
        headers["Content-Type"] = request.headers.get("content-type");
      } else {
        body = await request.text();
        diagnostics.bodyByteLength = new TextEncoder().encode(body).byteLength;
      }
    }
    // No browser cookies, authorization, content-length or hop-by-hop headers are copied.
    const backendPath = backendPathFromProxySegments(segments, new URL(request.url).search);
    const response = await backendRequest(backendPath, {
      method, body: body || undefined, headers,
      binary: isBinaryBackendProxyPath(normalizedPath, method),
    });
    return {
      status: response?.status || 200,
      payload: response?.payload ?? response ?? {},
      body: response?.body,
      contentType: response?.contentType,
      contentDisposition: response?.contentDisposition,
      diagnostics,
    };
  } catch (error) {
    const original = error.transportFailure ? error.cause : error;
    diagnostics.errorName = ERROR_NAMES.has(original?.name) ? original.name : "Error";
    diagnostics.errorCode = ERROR_CODES.has(original?.code) ? original.code : null;
    diagnostics.causeCode = ERROR_CODES.has(original?.cause?.code) ? original.cause.code : null;
    throw error;
  } finally {
    diagnostics.elapsedMs = Math.round(performance.now() - started);
    onDiagnostics(diagnostics);
  }
}

// Shared by the Next route and real HTTP integration tests, including error mapping.
export async function controlledBackendProxyResponse(request, context, dependencies) {
  let diagnostics;
  try {
    const result = await resolveBackendProxyRequest(request, context, {
      ...dependencies,
      onDiagnostics(value) {
        diagnostics = value;
        (dependencies.onDiagnostics || logProxyDiagnostics)(value);
      },
    });
    if ([204, 205, 304].includes(result.status)) return new Response(null, { status: result.status });
    if (result.body !== undefined && isBinaryBackendProxyPath(result.diagnostics.normalizedPath, request.method)) {
      const headers = new Headers({ "Content-Type": result.contentType || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      if (result.status < 400) headers.set("Content-Disposition", result.contentDisposition || 'attachment; filename="treasureland-report.xlsx"');
      return new Response(result.body, { status: result.status, headers });
    }
    return Response.json(result.payload ?? {}, { status: result.status });
  } catch (error) {
    const upload = diagnostics?.normalizedPath === "daily-sheet-imports/preview";
    const transportFailure = error.transportFailure || (!(error instanceof ApiError) && diagnostics?.mediaType === "multipart/form-data");
    const status = transportFailure ? 504 : error instanceof ApiError ? error.status : 500;
    const payload = error instanceof ApiError && error.exposePayload && error.payload && !transportFailure
      ? error.payload
      : { detail: transportFailure ? (upload ? UPLOAD_SERVICE_ERROR : PROXY_SERVICE_ERROR) : status >= 500 ? "Upstream service error." : error.message || "Request failed." };
    return Response.json(payload, { status });
  }
}
