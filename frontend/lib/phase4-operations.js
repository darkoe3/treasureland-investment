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
  return moneyNumber(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

export function calculateTransactionPreview(gameSales, isSubagent = false) {
  const netSales = Object.values(gameSales || {}).reduce((total, value) => total + moneyNumber(value), 0);
  const commission = netSales * 0.05;
  return {
    netSales,
    commission,
    toPay: netSales * 0.95,
    subagentShare: isSubagent ? netSales * 0.02 : 0,
    organisationShare: isSubagent ? netSales * 0.03 : 0,
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
