import { formatCurrency } from "./currency.js";

export function listFromPayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.results)) return payload.results;
  return [];
}

export function moneyNumber(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function moneyText(value) {
  return formatCurrency(moneyNumber(value));
}

export function roleAgencyIds(user) {
  if (user?.role === "SUPER_ADMIN") return null;
  return new Set((user?.agency_assignments || []).map((item) => item.agency.id));
}

export function canForAgency(user, agencyId, flag) {
  if (user?.role === "SUPER_ADMIN") return true;
  return (user?.agency_assignments || []).some((item) => item.agency.id === Number(agencyId) && item[flag]);
}

export function filterByVisibleAgency(items, user, agencyKey = "agency") {
  const ids = roleAgencyIds(user);
  if (!ids) return items;
  return items.filter((item) => ids.has(Number(item[agencyKey])));
}

export function searchablePersonText(person) {
  const codes = (person.tpm_codes || []).map((item) => item.code || item).join(" ");
  return `${person.full_name || ""} ${person.agency_name || ""} ${codes}`.toLowerCase();
}

export function searchPeople(people, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return people;
  return people.filter((person) => searchablePersonText(person).includes(needle));
}

export function activeTpmOptions(people) {
  return people.flatMap((person) =>
    (person.tpm_codes || [])
      .filter((code) => code.is_active !== false)
      .map((code) => ({
        id: code.id,
        code: code.code,
        person: person.id,
        person_name: person.full_name,
        agency: person.agency,
        agency_name: person.agency_name,
        agent_type: person.agent_type,
      })),
  );
}

// Integer minor-unit arithmetic avoids binary floating-point money calculations.
export function calculateTransactionPreview(gameSales, isSubagent = false, rate) {
  if (rate == null) return { netSales: "0.00", commission: "0.00", toPay: "0.00", subagentShare: "0.00", organisationShare: "0.00" };
  const scaled = (value, places) => {
    const match = String(value || "0").trim().match(/^\+?(\d*\.?\d+)(?:e([+-]?\d+))?$/i);
    if (!match) return 0n;
    const exponent = Number(match[2] || 0);
    if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 100) return 0n;
    const [whole, fraction = ""] = match[1].split(".");
    const digits = BigInt((whole || "0") + fraction);
    const shift = places + exponent - fraction.length;
    if (shift >= 0) return digits * (10n ** BigInt(shift));
    const divisor = 10n ** BigInt(-shift);
    return (digits + divisor / 2n) / divisor;
  };
  const net = Object.values(gameSales || {}).reduce((total, value) => total + scaled(value, 2), 0n);
  const basisPoints = scaled(rate, 4);
  const portion = (points) => (net * points + 5000n) / 10000n;
  const commission = portion(basisPoints);
  const format = (cents) => `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
  return {
    netSales: format(net), commission: format(commission),
    toPay: format(basisPoints === 500n ? portion(10000n - basisPoints) : net - commission),
    subagentShare: format(isSubagent ? portion(200n) : 0n),
    organisationShare: format(isSubagent ? portion(300n) : 0n),
  };
}

export function buildTransactionPayload(sheetId, tpmCodeId, sheetGames, gameSales) {
  return {
    daily_sheet: Number(sheetId),
    tpm_code: Number(tpmCodeId),
    sales: sheetGames.map((game) => ({
      daily_sheet_game: Number(game.id),
      amount: moneyNumber(gameSales[game.id]).toFixed(2),
    })),
  };
}

export function differenceLabel(value) {
  const amount = moneyNumber(value);
  if (amount > 0) return "Positive difference";
  if (amount < 0) return "Negative difference";
  return "Zero difference";
}

export function actionAvailability(user, sheet) {
  const editable = ["DRAFT", "RETURNED", "REOPENED"].includes(sheet?.status);
  return {
    canSubmit: editable && canForAgency(user, sheet?.agency, "can_edit"),
    canApprove: user?.role === "SUPER_ADMIN" && sheet?.status === "SUBMITTED",
    canReturn: user?.role === "SUPER_ADMIN" && sheet?.status === "SUBMITTED",
    canReopen: user?.role === "SUPER_ADMIN" && sheet?.status === "APPROVED",
  };
}
