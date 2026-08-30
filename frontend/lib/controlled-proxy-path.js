const COLLECTION_METHODS = {
  agencies: new Set(["GET"]),
  people: new Set(["GET", "POST"]),
  "tpm-codes": new Set(["GET", "POST"]),
  "daily-sheets": new Set(["GET", "POST"]),
  "tpm-daily-transactions": new Set(["GET", "POST"]),
  "omitted-terminals": new Set(["GET", "POST"]),
  "weekly-game-schedules": new Set(["GET"]),
  "audit-logs": new Set(["GET"]),
};

const DETAIL_METHODS = {
  people: new Set(["GET", "PATCH", "DELETE"]),
  "tpm-codes": new Set(["GET", "PATCH", "DELETE"]),
  "daily-sheets": new Set(["GET", "PATCH", "DELETE"]),
  "tpm-daily-transactions": new Set(["GET", "PATCH", "DELETE"]),
  "omitted-terminals": new Set(["GET", "PATCH", "DELETE"]),
};

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
  const parts = cleanPath.split("/").filter(Boolean);
  if (cleanPath === "games/for-date") {
    return normalizedMethod === "GET";
  }
  if (parts.length === 1) {
    return COLLECTION_METHODS[parts[0]]?.has(normalizedMethod) || false;
  }
  if (parts.length === 2 && /^\d+$/.test(parts[1])) {
    return DETAIL_METHODS[parts[0]]?.has(normalizedMethod) || false;
  }
  if (parts[0] === "daily-sheets" && parts.length === 3 && /^\d+$/.test(parts[1])) {
    const methods = {
      summary: new Set(["GET"]),
      submit: new Set(["POST"]),
      approve: new Set(["POST"]),
      return: new Set(["POST"]),
      reopen: new Set(["POST"]),
    };
    return methods[parts[2]]?.has(normalizedMethod) || false;
  }
  return false;
}

export function backendPathFromProxySegments(segments = [], search = "") {
  const path = segments.join("/").replace(/^\/+/, "").replace(/\/+$/, "");
  return `/${path}${search || ""}`;
}
