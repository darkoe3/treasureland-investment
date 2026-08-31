import { buildBackendUrl } from "./backend-url.js";
import { backendPathFromProxySegments, isAllowedBackendProxyPath, isBinaryBackendProxyPath } from "./controlled-proxy-path.js";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function normalizeProxySegments(segments = []) {
  const cleanSegments = (Array.isArray(segments) ? segments : [])
    .flatMap((segment) => String(segment || "").split("/"))
    .map((segment) => segment.trim())
    .filter(Boolean);

  if (cleanSegments[0] === "api" && cleanSegments[1] === "backend") {
    return cleanSegments.slice(2);
  }
  if (cleanSegments[0] === "backend") {
    return cleanSegments.slice(1);
  }
  return cleanSegments;
}

export function proxyDiagnostics({ method, rawSegments, segments, normalizedPath, allowed, backendPath }) {
  return {
    method,
    paramsPath: rawSegments,
    normalizedSegments: segments,
    normalizedPath,
    allowed,
    backendUrl: buildBackendUrl(backendPath),
  };
}

export async function resolveBackendProxyRequest(request, context, { cookieStore, validateCsrf, backendRequest }) {
  const method = String(request.method || "GET").toUpperCase();
  const params = await context.params;
  const rawSegments = params?.path || [];
  const segments = normalizeProxySegments(rawSegments);
  const normalizedPath = segments.join("/");
  const url = new URL(request.url);
  const backendPath = backendPathFromProxySegments(segments, url.search);
  const diagnostics = proxyDiagnostics({
    method,
    rawSegments,
    segments,
    normalizedPath,
    allowed: isAllowedBackendProxyPath(normalizedPath, method),
    backendPath,
  });

  if (UNSAFE_METHODS.has(method) && !validateCsrf(request, cookieStore)) {
    return { status: 403, payload: { detail: "Invalid security token." }, diagnostics };
  }

  if (!diagnostics.allowed) {
    return { status: 404, payload: { detail: "API path is not allowed." }, diagnostics };
  }

  const body = method === "GET" || method === "HEAD" ? undefined : await request.text();
  const response = await backendRequest(backendPath, {
    method,
    body: body || undefined,
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
}
