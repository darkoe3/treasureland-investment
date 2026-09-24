export const canManageAgencies = (user) => user?.role === "SUPER_ADMIN";
export function filterAgencies(rows, search, active) {
  const query = search.trim().toLowerCase();
  return rows.filter((row) => (!active || String(row.is_active) === active) &&
    `${row.name} ${row.code}`.toLowerCase().includes(query));
}
export function agencyConfirmationReady(mode, draft, impact) {
  if (mode === "create") return !!draft.name.trim() && !!draft.code.trim();
  if (mode === "edit") return !!draft.name.trim() && !!draft.code.trim() && (!draft.codeChanged || draft.confirm_code_change);
  return !!draft.reason.trim() && draft.confirmed &&
    (mode !== "deactivate" || !impact?.editable_daily_sheets || draft.acknowledge_editable_sheets);
}
