export function listFromApiPayload(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (Array.isArray(payload?.results)) {
    return payload.results;
  }
  return [];
}

export function activeAgenciesFromPayload(payload) {
  return listFromApiPayload(payload).filter((agency) => agency.is_active !== false);
}

export function buildAssignmentRows(accountant, agencies) {
  const existing = new Map((accountant?.agency_assignments || []).map((item) => [item.agency.id, item]));
  return agencies.map((agency) => {
    const assignment = existing.get(agency.id);
    return {
      agency: agency.id,
      agency_name: agency.name,
      selected: Boolean(assignment),
      can_create: assignment?.can_create || false,
      can_edit: assignment?.can_edit || false,
      can_delete: assignment?.can_delete || false,
      can_export: assignment?.can_export || false,
      can_view_history: assignment?.can_view_history || false,
    };
  });
}

export function shouldSyncAgencyAssignments(editing, agencyLoadError) {
  return Boolean(editing && !agencyLoadError);
}
