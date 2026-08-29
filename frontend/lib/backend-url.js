export function apiBaseUrl(value = process.env.API_BASE_URL || "http://127.0.0.1:8000/api") {
  return value.replace(/\/+$/, "");
}

export function normalizeBackendPath(path, base = apiBaseUrl()) {
  const [rawPath, rawQuery = ""] = String(path || "").split("?");
  const basePath = new URL(base).pathname.replace(/\/+$/, "");
  let pathname = rawPath.replace(/^\/+/, "");

  if (basePath.endsWith("/api") && (pathname === "api" || pathname.startsWith("api/"))) {
    pathname = pathname.replace(/^api\/?/, "");
  }

  if (pathname && !pathname.endsWith("/")) {
    pathname = `${pathname}/`;
  }

  const query = rawQuery ? `?${rawQuery}` : "";
  return `/${pathname}${query}`;
}

export function buildBackendUrl(path, base = apiBaseUrl()) {
  return `${apiBaseUrl(base)}${normalizeBackendPath(path, base)}`;
}
