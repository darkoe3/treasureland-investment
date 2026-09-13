export function sheetControls(user, sheet) {
  const admin = user?.role === "SUPER_ADMIN";
  return {
    reset: admin && !sheet.is_archived && ["DRAFT", "RETURNED", "REOPENED"].includes(sheet.status) && sheet.can_reset === true,
    delete: admin && sheet.status === "DRAFT" && !sheet.is_archived && sheet.can_delete === true,
    guidance: !admin ? "" : sheet.status === "SUBMITTED" ? "Return this sheet before resetting it." : sheet.status === "APPROVED" ? "Reopen this sheet before resetting it." : "",
  };
}
export function canConfirmSheetAction(reason, confirmed, busy) {
  return Boolean(reason.trim() && confirmed && !busy);
}
