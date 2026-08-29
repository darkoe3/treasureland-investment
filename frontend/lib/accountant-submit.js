import { clientRequest, apiPath } from "./client-api.js";
import { shouldSyncAgencyAssignments } from "./resource-shapes.js";

export const ACCOUNTANT_ID_ERROR = "Accountant profile saved, but the app could not confirm a valid accountant ID. Please refresh and try again.";

export function positiveNumericId(value) {
  if (Number.isInteger(value) && value > 0) {
    return String(value);
  }
  if (typeof value === "string" && /^[1-9]\d*$/.test(value.trim())) {
    return value.trim();
  }
  return "";
}

export function resolveAccountantId({ editing, accountant, saved }) {
  if (editing) {
    return positiveNumericId(accountant?.id);
  }
  return positiveNumericId(saved?.id);
}

export async function saveAccountantWithAssignments({
  editing,
  accountant,
  profile,
  selectedAssignments,
  agencyLoadError = "",
  request = clientRequest,
}) {
  const existingId = positiveNumericId(accountant?.id);
  if (editing && !existingId) {
    return { ok: false, internalError: ACCOUNTANT_ID_ERROR, saved: null, accountantId: "" };
  }

  const saved = editing
    ? await request(apiPath(`accountants/${existingId}/`), {
        method: "PATCH",
        body: JSON.stringify({ full_name: profile.fullName, email: profile.email, is_active: profile.isActive }),
      })
    : await request(apiPath("accountants/"), {
        method: "POST",
        body: JSON.stringify({
          full_name: profile.fullName,
          email: profile.email,
          password: profile.password,
          is_active: profile.isActive,
          agency_assignments: selectedAssignments,
        }),
      });

  const accountantId = resolveAccountantId({ editing, accountant, saved });
  if (!accountantId) {
    return { ok: false, internalError: ACCOUNTANT_ID_ERROR, saved, accountantId: "" };
  }

  if (shouldSyncAgencyAssignments(editing, agencyLoadError)) {
    try {
      await request(apiPath(`accountants/${accountantId}/set-agencies/`), {
        method: "POST",
        body: JSON.stringify({ agency_assignments: selectedAssignments }),
      });
    } catch (assignmentError) {
      return { ok: false, assignmentError, saved, accountantId };
    }
  }

  return { ok: true, saved, accountantId };
}
