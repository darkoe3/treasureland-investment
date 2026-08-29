const ALLOWED_PREFIXES = [
  "agencies",
  "daily-sheets",
  "games/for-date",
  "people",
  "tpm-codes",
  "weekly-game-schedules",
  "audit-logs",
];

const ACCOUNTANT_ACTION_METHODS = new Map([
  ["set-agencies", new Set(["POST"])],
  ["reset-password", new Set(["POST"])],
  ["activate", new Set(["POST"])],
  ["deactivate", new Set(["POST"])],
]);

function cleanProxyPath(path) {
  return String(path || "").split("?")[0].replace(/^\/+/, "").replace(/\/+$/, "");
}

function isAccountantPathAllowed(path, method) {
  const parts = cleanProxyPath(path).split("/").filter(Boolean);
  if (parts[0] !== "accountants") {
    return false;
  }
  if (parts.length === 1) {
    return new Set(["GET", "POST"]).has(method);
  }
  if (parts.length === 2 && /^\d+$/.test(parts[1])) {
    return new Set(["GET", "PATCH"]).has(method);
  }
  if (parts.length === 3 && /^\d+$/.test(parts[1])) {
    return ACCOUNTANT_ACTION_METHODS.get(parts[2])?.has(method) || false;
  }
  return false;
}

export function isAllowedBackendProxyPath(path, method = "GET") {
  const normalizedMethod = String(method || "GET").toUpperCase();
  const cleanPath = cleanProxyPath(path);
  if (isAccountantPathAllowed(cleanPath, normalizedMethod)) {
    return true;
  }
  return ALLOWED_PREFIXES.some((prefix) => cleanPath === prefix || cleanPath.startsWith(`${prefix}/`));
}

export function backendPathFromProxySegments(segments = [], search = "") {
  const path = segments.join("/").replace(/^\/+/, "").replace(/\/+$/, "");
  return `/${path}${search || ""}`;
}
