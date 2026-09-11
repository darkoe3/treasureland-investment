import { canForAgency } from "./phase4-operations.js";

export const defaultPeopleFilters = { query: "", agency: "", status: "all", showInactive: true };

export function filterPeople(people, filters) {
  const needle = filters.query.trim().toLowerCase();
  return people.flatMap((person) => {
    if (filters.agency && Number(person.agency) !== Number(filters.agency)) return [];
    if (filters.status !== "all" && person.is_active !== (filters.status === "active")) return [];
    const codes = (person.tpm_codes || []).filter((code) => filters.showInactive || code.is_active);
    const personMatches = `${person.full_name} ${person.agency_name}`.toLowerCase().includes(needle);
    const visibleCodes = personMatches ? codes : codes.filter((code) => code.code.toLowerCase().includes(needle));
    if (!personMatches && !visibleCodes.length) return [];
    return [{ ...person, visibleCodes }];
  });
}

export function codeActions(user, person, code) {
  const editable = canForAgency(user, person.agency, "can_edit");
  return [
    ...(editable ? ["edit", "reassign"] : []),
    ...(code.is_active && canForAgency(user, person.agency, "can_delete") ? ["deactivate"] : []),
    ...(!code.is_active && editable ? ["reactivate"] : []),
  ];
}

export function fieldErrors(error) {
  if (error.status < 400 || error.status >= 500 || !error.payload || typeof error.payload !== "object") return {};
  const messages = (value) => typeof value === "string" ? value : Array.isArray(value) ? value.map(messages).filter(Boolean).join(" ") : "";
  return Object.fromEntries(Object.entries(error.payload).map(([key, value]) => [key, messages(value)]));
}

export function editorRequest(editor, draft) {
  if (editor.kind === "person") {
    return {
      path: editor.person ? `/people/${editor.person.id}/` : "/people/",
      method: editor.person ? "PATCH" : "POST",
      payload: { full_name: draft.full_name, agency: Number(draft.agency), agent_type: draft.agent_type, is_active: draft.is_active },
      success: editor.person ? "Person updated." : "Person created.",
    };
  }
  if (editor.kind === "reassign") {
    return { path: `/tpm-codes/${editor.code.id}/`, method: "PATCH",
      payload: { person: Number(draft.person), is_active: draft.is_active, confirm_reassignment: true },
      success: `TPM code ${editor.code.code} reassigned.` };
  }
  return {
    path: editor.code ? `/tpm-codes/${editor.code.id}/` : "/tpm-codes/",
    method: editor.code ? "PATCH" : "POST",
    // Editing a code deliberately omits ownership and status changes.
    payload: editor.code ? { code: draft.code } : { person: Number(draft.person), code: draft.code, is_active: draft.is_active },
    success: editor.code ? "TPM code updated." : "TPM code added.",
  };
}

export async function submitPeopleEditor(editor, draft, people, request, confirm) {
  if (editor.kind === "reassign") {
    const target = people.find((person) => person.id === Number(draft.person));
    if (!target || target.id === editor.person.id) throw new Error("Select a different person for this TPM code.");
    if (!confirm(`Reassign TPM code ${editor.code.code} from ${editor.person.full_name} (${editor.person.agency_name}) to ${target.full_name} (${target.agency_name})? It will be ${draft.is_active ? "active" : "inactive"}. Historical daily sheets will be preserved.`)) return null;
  }
  const operation = editorRequest(editor, draft);
  await request(operation.path, { method: operation.method, body: JSON.stringify(operation.payload) });
  return operation.success;
}

export async function changeCodeStatus(person, code, request, confirm) {
  if (code.is_active && !confirm(`Deactivate TPM code ${code.code} assigned to ${person.full_name}? Transaction history will be preserved.`)) return null;
  await request(`/tpm-codes/${code.id}/`, code.is_active
    ? { method: "DELETE" }
    : { method: "PATCH", body: JSON.stringify({ is_active: true }) });
  return `TPM code ${code.code} ${code.is_active ? "deactivated" : "reactivated"}.`;
}
