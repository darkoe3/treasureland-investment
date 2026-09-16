export function terminalChoices(people, agency, person) {
  const scoped = people.filter((item) => String(item.agency) === String(agency) && item.is_active);
  const owner = scoped.find((item) => String(item.id) === String(person));
  return { people: scoped, codes: (owner?.tpm_codes || []).filter((code) => code.is_active) };
}

export function changeTerminalDraft(draft, field, value) {
  return { ...draft, [field]: value, ...(field === "agency" ? { person: "", sub_agent_number: "" } : {}),
    ...(field === "person" ? { sub_agent_number: "" } : {}), confirmed: false };
}

export function terminalPayload(draft, mode) {
  if (mode === "edit") return { terminal_number: draft.terminal_number.trim() };
  if (!draft.agency || !draft.person || !draft.sub_agent_number) throw new Error("Select Agency, Person and Sub-Agent Number.");
  const owner = { agency: Number(draft.agency), person: Number(draft.person), sub_agent_number: Number(draft.sub_agent_number) };
  if (mode === "reassign") {
    if (!draft.reason?.trim() || !draft.confirmed) throw new Error("Enter a reason and explicitly confirm reassignment.");
    return { ...owner, reason: draft.reason.trim(), confirmed: true };
  }
  return { ...owner, terminal_number: draft.terminal_number.trim(), is_active: draft.is_active };
}

export function canConfirmTerminalImport(batch, confirmed, now = Date.now()) {
  return Boolean(batch && batch.status === "PREVIEWED" && !batch.errors?.length &&
    new Date(batch.expires_at).getTime() > now && confirmed);
}

export function terminalActions(user, terminal) {
  return user.role === "SUPER_ADMIN" ? ["Edit", "Reassign", terminal.is_active ? "Deactivate" : "Reactivate", "View history"] : [];
}
