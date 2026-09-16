const COLLECTION_METHODS = {
  "terminal-numbers": new Set(["GET", "POST"]),
  agencies: new Set(["GET"]),
  games: new Set(["GET"]),
  people: new Set(["GET", "POST"]),
  "tpm-codes": new Set(["GET", "POST"]),
  "daily-sheets": new Set(["GET", "POST"]),
  "tpm-daily-transactions": new Set(["GET", "POST"]),
  "omitted-terminals": new Set(["GET", "POST"]),
  "weekly-game-schedules": new Set(["GET", "POST"]),
  "audit-logs": new Set(["GET"]),
};

const DETAIL_METHODS = {
  "terminal-numbers": new Set(["GET", "PATCH"]),
  people: new Set(["GET", "PATCH", "DELETE"]),
  "tpm-codes": new Set(["GET", "PATCH", "DELETE"]),
  "daily-sheets": new Set(["GET", "PATCH", "DELETE"]),
  "tpm-daily-transactions": new Set(["GET", "PATCH", "DELETE"]),
  "omitted-terminals": new Set(["GET", "PATCH", "DELETE"]),
  "weekly-game-schedules": new Set(["GET", "PATCH", "DELETE"]),
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

function isReportPathAllowed(path, method) {
  if (method !== "GET") {
    return false;
  }
  return path === "reports/agency-summary" || path === "reports/agency-summary/export";
}

function isDailySheetImportPathAllowed(path, method) {
  const parts = cleanProxyPath(path).split("/").filter(Boolean);
  if (parts.length === 2 && parts[0] === "daily-sheet-imports" && parts[1] === "preview") {
    return method === "POST";
  }
  if (parts.length === 2 && parts[0] === "daily-sheet-imports" && parts[1] === "template") {
    return method === "GET";
  }
  if (parts.length === 2 && parts[0] === "daily-sheet-imports" && /^\d+$/.test(parts[1])) {
    return method === "GET";
  }
  if (parts.length === 3 && parts[0] === "daily-sheet-imports" && /^\d+$/.test(parts[1])) {
    return new Set(["confirm", "cancel"]).has(parts[2]) && method === "POST";
  }
  return false;
}

export function isAllowedBackendProxyPath(path, method = "GET") {
  const normalizedMethod = String(method || "GET").toUpperCase();
  const cleanPath = cleanProxyPath(path);
  if (isReportPathAllowed(cleanPath, normalizedMethod)) {
    return true;
  }
  if (isAccountantPathAllowed(cleanPath, normalizedMethod)) {
    return true;
  }
  if (isDailySheetImportPathAllowed(cleanPath, normalizedMethod)) {
    return true;
  }
  if (/^terminal-number-imports\/(preview)$/.test(cleanPath)) return normalizedMethod === "POST";
  if (/^terminal-number-imports\/(template|\d+)$/.test(cleanPath)) return normalizedMethod === "GET";
  if (/^terminal-number-imports\/\d+\/(confirm|cancel)$/.test(cleanPath)) return normalizedMethod === "POST";
  if (/^terminal-numbers\/\d+\/history$/.test(cleanPath)) return normalizedMethod === "GET";
  if (/^terminal-numbers\/\d+\/(deactivate|reactivate|reassign)$/.test(cleanPath)) return normalizedMethod === "POST";
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
      reset: new Set(["POST"]),
    };
    return methods[parts[2]]?.has(normalizedMethod) || false;
  }
  return false;
}

export function backendPathFromProxySegments(segments = [], search = "") {
  const path = segments.join("/").replace(/^\/+/, "").replace(/\/+$/, "");
  return `/${path}${search || ""}`;
}

export function isBinaryBackendProxyPath(path, method = "GET") {
  const cleanPath = cleanProxyPath(path);
  const normalizedMethod = String(method || "GET").toUpperCase();
  return (cleanPath === "reports/agency-summary/export" || cleanPath === "daily-sheet-imports/template" || cleanPath === "terminal-number-imports/template") && normalizedMethod === "GET";
}
