"use client";

import { Edit3, Plus, Power, Save, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { canForAgency, listFromPayload, searchPeople } from "../lib/phase4-operations";

const emptyPerson = { id: null, agency: "", full_name: "", agent_type: "MAIN_AGENT", is_active: true };

export default function PeopleTpmClient({ user, initialAgencies = [] }) {
  const [agencies] = useState(initialAgencies);
  const [people, setPeople] = useState([]);
  const [query, setQuery] = useState("");
  const [agencyFilter, setAgencyFilter] = useState("");
  const [personForm, setPersonForm] = useState(emptyPerson);
  const [codeForm, setCodeForm] = useState({ person: "", code: "" });
  const [editingCode, setEditingCode] = useState(null);
  const [state, setState] = useState({ loading: true, error: "", success: "" });

  async function loadPeople() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set("search", query.trim());
      const payload = await clientRequest(apiPath(`/people/${params.toString() ? `?${params}` : ""}`));
      setPeople(listFromPayload(payload));
      setState((current) => ({ ...current, loading: false }));
    } catch (error) {
      setState({ loading: false, error: error.message, success: "" });
    }
  }

  useEffect(() => {
    queueMicrotask(() => {
      loadPeople();
    });
    // Initial load only; later loads are user-triggered so search text is not refetched on every keypress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visiblePeople = useMemo(() => {
    const filtered = agencyFilter ? people.filter((person) => Number(person.agency) === Number(agencyFilter)) : people;
    return searchPeople(filtered, query);
  }, [people, agencyFilter, query]);

  async function savePerson(event) {
    event.preventDefault();
    const editing = Boolean(personForm.id);
    try {
      const payload = {
        agency: Number(personForm.agency),
        full_name: personForm.full_name,
        agent_type: personForm.agent_type,
        is_active: Boolean(personForm.is_active),
      };
      await clientRequest(apiPath(editing ? `/people/${personForm.id}/` : "/people/"), {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      setPersonForm(emptyPerson);
      setState({ loading: false, error: "", success: editing ? "Person updated." : "Person created." });
      await loadPeople();
    } catch (error) {
      setState({ loading: false, error: error.message, success: "" });
    }
  }

  async function saveCode(event) {
    event.preventDefault();
    try {
      await clientRequest(apiPath(editingCode ? `/tpm-codes/${editingCode.id}/` : "/tpm-codes/"), {
        method: editingCode ? "PATCH" : "POST",
        body: JSON.stringify({ person: Number(codeForm.person), code: codeForm.code, is_active: true }),
      });
      setCodeForm({ person: "", code: "" });
      setEditingCode(null);
      setState({ loading: false, error: "", success: editingCode ? "TPM code updated." : "TPM code added." });
      await loadPeople();
    } catch (error) {
      setState({ loading: false, error: error.message, success: "" });
    }
  }

  async function deactivateCode(code) {
    if (!window.confirm(`Deactivate TPM code ${code.code}? Transaction history will be preserved.`)) return;
    await clientRequest(apiPath(`/tpm-codes/${code.id}/`), { method: "DELETE" });
    setState({ loading: false, error: "", success: "TPM code deactivated." });
    await loadPeople();
  }

  const selectableAgencies = agencies.filter((agency) => canForAgency(user, agency.id, personForm.id ? "can_edit" : "can_create"));

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="toolbar">
          <label className="search-box">
            <Search size={18} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name or TPM code" />
          </label>
          <select value={agencyFilter} onChange={(event) => setAgencyFilter(event.target.value)} aria-label="Filter by agency">
            <option value="">All accessible agencies</option>
            {agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
          </select>
          <button className="secondary-button" type="button" onClick={loadPeople}>Refresh</button>
        </div>
        {state.error ? <p className="form-error">{state.error}</p> : null}
        {state.success ? <p className="form-success">{state.success}</p> : null}
      </section>

      <section className="form-grid">
        <form className="panel form-panel" onSubmit={savePerson}>
          <div className="panel-heading"><h2>{personForm.id ? "Edit Person" : "Create Person"}</h2></div>
          <div className="field-grid">
            <label className="field-group">Agency
              <select required value={personForm.agency} onChange={(event) => setPersonForm({ ...personForm, agency: event.target.value })}>
                <option value="">Select agency</option>
                {selectableAgencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
              </select>
            </label>
            <label className="field-group">Status
              <select value={personForm.is_active ? "true" : "false"} onChange={(event) => setPersonForm({ ...personForm, is_active: event.target.value === "true" })}>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
            </label>
            <label className="field-group">Name
              <input required value={personForm.full_name} onChange={(event) => setPersonForm({ ...personForm, full_name: event.target.value })} />
            </label>
            <label className="field-group">Agent status
              <select value={personForm.agent_type} onChange={(event) => setPersonForm({ ...personForm, agent_type: event.target.value })}>
                <option value="MAIN_AGENT">Main Agent</option>
                <option value="SUBAGENT">Sub-agent</option>
              </select>
            </label>
          </div>
          <div className="button-row">
            <button className="primary-button" type="submit"><Save size={16} />Save person</button>
            {personForm.id ? <button className="secondary-button" type="button" onClick={() => setPersonForm(emptyPerson)}>Cancel</button> : null}
          </div>
        </form>

        <form className="panel form-panel" onSubmit={saveCode}>
          <div className="panel-heading"><h2>{editingCode ? "Edit TPM Code" : "Add TPM Code"}</h2></div>
          <label className="field-group">Person
            <select required value={codeForm.person} onChange={(event) => setCodeForm({ ...codeForm, person: event.target.value })}>
              <option value="">Select person</option>
              {people.map((person) => <option key={person.id} value={person.id}>{person.full_name} - {person.agency_name}</option>)}
            </select>
          </label>
          <label className="field-group">TPM Code
            <input required value={codeForm.code} onChange={(event) => setCodeForm({ ...codeForm, code: event.target.value })} />
          </label>
          <div className="button-row">
            <button className="primary-button" type="submit"><Plus size={16} />{editingCode ? "Save code" : "Add code"}</button>
            {editingCode ? <button className="secondary-button" type="button" onClick={() => { setEditingCode(null); setCodeForm({ person: "", code: "" }); }}>Cancel</button> : null}
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>People & TPM Codes</h2><span>{visiblePeople.length} shown</span></div>
        <div className="table-wrap responsive-table">
          <table>
            <thead><tr><th>Name</th><th>Agency</th><th>Status</th><th>TPM Codes</th><th>Actions</th></tr></thead>
            <tbody>
              {state.loading ? <tr><td colSpan="5" className="empty-cell">Loading people...</td></tr> : null}
              {!state.loading && !visiblePeople.length ? <tr><td colSpan="5" className="empty-cell">No people match your filters.</td></tr> : null}
              {visiblePeople.map((person) => (
                <tr key={person.id}>
                  <td data-label="Name">{person.full_name}<br /><small>{person.agent_type === "SUBAGENT" ? "Sub-agent" : "Main Agent"}</small></td>
                  <td data-label="Agency">{person.agency_name}</td>
                  <td data-label="Status"><span className={`status-pill ${person.is_active ? "submitted" : "empty"}`}>{person.is_active ? "Active" : "Inactive"}</span></td>
                  <td data-label="TPM Codes">
                    <div className="chip-wrap">{(person.tpm_codes || []).map((code) => <span className={`mini-chip ${code.is_active ? "" : "muted"}`} key={code.id}>{code.code}</span>)}</div>
                  </td>
                  <td data-label="Actions">
                    <div className="button-row compact">
                      <button className="icon-button" title="Edit person" type="button" onClick={() => setPersonForm(person)}><Edit3 size={16} /></button>
                      {(person.tpm_codes || []).map((code) => (
                        <span className="button-row compact" key={code.id}>
                          <button className="icon-button" title={`Edit ${code.code}`} type="button" onClick={() => { setEditingCode(code); setCodeForm({ person: person.id, code: code.code }); }} disabled={!code.is_active}>
                            <Edit3 size={16} />
                          </button>
                          <button className="icon-button" title={`Deactivate ${code.code}`} type="button" onClick={() => deactivateCode(code)} disabled={!code.is_active}>
                            <Power size={16} />
                          </button>
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
