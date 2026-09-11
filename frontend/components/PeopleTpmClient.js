"use client";

import { ArrowRightLeft, Building2, CheckCircle2, Edit3, LoaderCircle, Plus, Power, RotateCcw, Save, Search, Users, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { canForAgency, filterByVisibleAgency, listFromPayload } from "../lib/phase4-operations";
import { changeCodeStatus, codeActions, defaultPeopleFilters, fieldErrors, filterPeople, submitPeopleEditor } from "../lib/people-tpm-operations";

const request = (path, options) => clientRequest(apiPath(path), options);
const actionDetails = { edit: [Edit3, "Edit", "secondary"], reassign: [ArrowRightLeft, "Reassign", "secondary"], deactivate: [Power, "Deactivate", "warning"], reactivate: [CheckCircle2, "Reactivate", "success"] };

function Badge({ active }) {
  return <span className={`people-status ${active ? "is-active" : "is-inactive"}`}><span aria-hidden="true" />{active ? "Active" : "Inactive"}</span>;
}

function Field({ name, label, errors, children }) {
  const error = errors[name];
  const attributes = { id: `people-${name}`, "aria-invalid": Boolean(error), "aria-describedby": error ? `people-${name}-error` : undefined };
  return <div className="people-field"><label htmlFor={attributes.id}>{label}</label>{children(attributes)}{error ? <p className="people-field-error" id={`people-${name}-error`}>{error}</p> : null}</div>;
}

export default function PeopleTpmClient({ user, initialAgencies = [] }) {
  const [people, setPeople] = useState([]);
  const [filters, setFilters] = useState({ ...defaultPeopleFilters });
  const [editor, setEditor] = useState(null);
  const [draft, setDraft] = useState({});
  const [errors, setErrors] = useState({});
  const [state, setState] = useState({ loading: true, error: "", success: "" });
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const trigger = useRef(null);
  const editorHeading = useRef(null);
  const pageHeading = useRef(null);
  const alert = useRef(null);

  async function loadPeople() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const payload = await request("/people/");
      setPeople(listFromPayload(payload));
      setState((current) => ({ ...current, loading: false }));
    } catch (error) {
      setState((current) => ({ ...current, loading: false, error: error.message }));
    }
  }

  useEffect(() => { queueMicrotask(loadPeople); }, []);
  useEffect(() => {
    if (editor) {
      editorHeading.current?.focus();
      editorHeading.current?.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }, [editor]);
  useEffect(() => { if (state.error) alert.current?.focus(); }, [state.error]);

  const agencies = filterByVisibleAgency(initialAgencies, user, "id");
  const accessiblePeople = useMemo(() => filterByVisibleAgency(people, user), [people, user]);
  const visiblePeople = useMemo(() => filterPeople(accessiblePeople, filters), [accessiblePeople, filters]);
  const codeCount = visiblePeople.reduce((total, person) => total + person.visibleCodes.length, 0);
  const canCreate = agencies.some((agency) => canForAgency(user, agency.id, "can_create"));
  const blocked = pending || state.loading;
  const actionsBlocked = blocked || Boolean(editor);
  useEffect(() => {
    if (!editor && !blocked && trigger.current) {
      (trigger.current.isConnected ? trigger.current : pageHeading.current)?.focus();
      trigger.current = null;
    }
  }, [editor, blocked]);
  const selectableAgencies = agencies.filter((agency) => canForAgency(user, agency.id, editor?.person ? "can_edit" : "can_create"));
  const selectablePeople = accessiblePeople.filter((person) => canForAgency(user, person.agency, editor?.code ? "can_edit" : "can_create") && (editor?.kind !== "reassign" || person.id !== editor.person.id));
  const target = accessiblePeople.find((person) => person.id === Number(draft.person));
  const editorTitle = editor?.kind === "person" ? `${editor.person ? "Edit" : "Add"} Person` : editor?.kind === "reassign" ? "Reassign TPM Code" : `${editor?.code ? "Edit" : "Add"} TPM Code`;

  function openEditor(kind, person = null, code = null, event) {
    if (busy.current || state.loading || editor) return;
    trigger.current = event.currentTarget;
    setErrors({});
    setState((current) => ({ ...current, error: "", success: "" }));
    setDraft(kind === "person"
      ? { full_name: person?.full_name || "", agency: person?.agency || "", agent_type: person?.agent_type || "MAIN_AGENT", is_active: person?.is_active ?? true }
      : { person: kind === "reassign" ? "" : person?.id || "", code: code?.code || "", is_active: code?.is_active ?? true });
    setEditor({ kind, person, code });
  }

  function closeEditor() {
    setEditor(null);
    setErrors({});
  }

  async function save(event) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setErrors({});
    setState((current) => ({ ...current, error: "", success: "" }));
    try {
      const success = await submitPeopleEditor(editor, draft, accessiblePeople, request, (message) => window.confirm(message));
      if (success) {
        closeEditor();
        setState((current) => ({ ...current, success }));
        await loadPeople();
      }
    } catch (error) {
      setErrors(fieldErrors(error));
      setState((current) => ({ ...current, error: error.message }));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  async function setCodeStatus(person, code) {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setState((current) => ({ ...current, error: "", success: "" }));
    try {
      const success = await changeCodeStatus(person, code, request, (message) => window.confirm(message));
      if (success) {
        setState((current) => ({ ...current, success }));
        await loadPeople();
      }
    } catch (error) {
      setState((current) => ({ ...current, error: error.message }));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  const updateDraft = (name, value) => setDraft((current) => ({ ...current, [name]: value }));
  const updateFilter = (name, value) => setFilters((current) => ({ ...current, [name]: value }));
  const resetFilters = () => setFilters({ ...defaultPeopleFilters });

  return (
    <div className="people-page">
      <header className="people-page-header">
        <div><p className="people-eyebrow">People directory</p><h1 ref={pageHeading} tabIndex={-1}>People &amp; TPM Codes</h1><p>Each person can have multiple TPM codes. Manage their details, codes and assignments here.</p></div>
        <div className="people-actions">
          {canCreate ? <button className="people-button primary" disabled={actionsBlocked} onClick={(event) => openEditor("person", null, null, event)}><Users size={18} aria-hidden="true" />Add Person</button> : null}
          {canCreate ? <button className="people-button primary" disabled={actionsBlocked || !accessiblePeople.some((person) => canForAgency(user, person.agency, "can_create"))} onClick={(event) => openEditor("code", null, null, event)}><Plus size={18} aria-hidden="true" />Add TPM Code</button> : null}
        </div>
      </header>

      <section className="people-filters" aria-label="Search and filters">
        <div className="people-field people-search"><label htmlFor="people-search">Search people or TPM codes</label><div><Search size={18} aria-hidden="true" /><input id="people-search" type="search" placeholder="Name or TPM code" value={filters.query} onChange={(event) => updateFilter("query", event.target.value)} /></div></div>
        <div className="people-field"><label htmlFor="people-agency-filter">Agency</label><select id="people-agency-filter" value={filters.agency} onChange={(event) => updateFilter("agency", event.target.value)}><option value="">All accessible agencies</option>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></div>
        <div className="people-field"><label htmlFor="people-status-filter">Person status</label><select id="people-status-filter" value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}><option value="all">All statuses</option><option value="active">Active</option><option value="inactive">Inactive</option></select></div>
        <label className="people-checkbox"><input type="checkbox" checked={filters.showInactive} onChange={(event) => updateFilter("showInactive", event.target.checked)} />Show inactive TPM codes</label>
        <button className="people-button secondary" onClick={resetFilters}><RotateCcw size={16} aria-hidden="true" />Reset filters</button>
      </section>

      {state.success ? <p className="people-alert people-alert-success form-success" role="status"><CheckCircle2 size={20} aria-hidden="true" />{state.success}</p> : null}
      {state.error ? <div className="people-alert people-alert-error form-error" role="alert" tabIndex={-1} ref={alert}>{state.error}</div> : null}
      <span className="sr-only" role="status">{pending ? "Saving changes. Please wait." : ""}</span>

      {editor ? <section className="people-editor" aria-labelledby="people-editor-title">
        <div className="people-section-heading"><div><p className="people-eyebrow">{editor.kind === "person" ? "Person details" : "TPM code details"}</p><h2 id="people-editor-title" ref={editorHeading} tabIndex={-1}>{editorTitle}</h2></div><button className="people-button secondary" type="button" disabled={pending} onClick={closeEditor}><X size={16} aria-hidden="true" />Cancel</button></div>
        {editor.code ? <dl className="people-assignment-summary"><div><dt>TPM code</dt><dd>{editor.code.code}</dd></div><div><dt>Current person</dt><dd>{editor.person.full_name}</dd></div><div><dt>Current agency</dt><dd>{editor.person.agency_name}</dd></div><div><dt>Current status</dt><dd><Badge active={editor.code.is_active} /></dd></div></dl> : null}
        <form onSubmit={save} aria-busy={pending}>
          <fieldset disabled={pending} className="people-form-fields">
            <legend className="sr-only">{editorTitle}</legend>
            {editor.kind === "person" ? <>
              <Field name="full_name" label="Full name" errors={errors}>{(attrs) => <input {...attrs} required maxLength={255} value={draft.full_name} onChange={(event) => updateDraft("full_name", event.target.value)} />}</Field>
              <Field name="agency" label="Agency" errors={errors}>{(attrs) => <select {...attrs} required value={draft.agency} onChange={(event) => updateDraft("agency", event.target.value)}><option value="">Select agency</option>{selectableAgencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select>}</Field>
              <Field name="agent_type" label="Agent type" errors={errors}>{(attrs) => <select {...attrs} value={draft.agent_type} onChange={(event) => updateDraft("agent_type", event.target.value)}><option value="MAIN_AGENT">Main Agent</option><option value="SUBAGENT">Sub-agent</option></select>}</Field>
            </> : <>
              {!editor.code || editor.kind === "reassign" ? <Field name="person" label={editor.kind === "reassign" ? "New person" : "Person"} errors={errors}>{(attrs) => <select {...attrs} required value={draft.person} onChange={(event) => updateDraft("person", event.target.value)}><option value="">Select person</option>{selectablePeople.map((person) => <option key={person.id} value={person.id}>{person.full_name} — {person.agency_name}</option>)}</select>}</Field> : null}
              {editor.kind !== "reassign" ? <Field name="code" label="TPM code" errors={errors}>{(attrs) => <input {...attrs} required maxLength={80} value={draft.code} onChange={(event) => updateDraft("code", event.target.value)} />}</Field> : <div className="people-field"><span>New agency</span><p className="people-readonly">{target?.agency_name || "Select a new person to see their agency."}</p></div>}
            </>}
            {editor.kind === "person" || !editor.code || editor.kind === "reassign" ? <Field name="is_active" label={editor.kind === "person" ? "Person status" : "TPM status after saving"} errors={errors}>{(attrs) => <select {...attrs} value={draft.is_active ? "true" : "false"} onChange={(event) => updateDraft("is_active", event.target.value === "true")}><option value="true">Active</option><option value="false">Inactive</option></select>}</Field> : null}
          </fieldset>
          {editor.kind === "reassign" ? <p className="people-help">You will confirm the new assignment before saving. Historical daily sheets will be preserved.</p> : null}
          {errors.confirm_reassignment ? <p className="people-field-error">{errors.confirm_reassignment}</p> : null}
          <div className="people-actions people-editor-footer"><button className="people-button primary" type="submit" disabled={pending || (editor.kind === "reassign" && !draft.person)}>{pending ? <LoaderCircle size={17} aria-hidden="true" /> : <Save size={17} aria-hidden="true" />}{pending ? "Saving…" : "Save"}</button><button className="people-button secondary" type="button" disabled={pending} onClick={closeEditor}>Cancel</button></div>
        </form>
      </section> : null}

      <section aria-labelledby="people-results-title" aria-busy={state.loading}>
        <div className="people-section-heading people-results-heading"><div><h2 id="people-results-title">People directory</h2><p role="status">{state.loading ? "Loading people…" : `${visiblePeople.length} matching people · ${codeCount} matching TPM codes`}</p></div><button className="people-button secondary" disabled={blocked} onClick={loadPeople}><RotateCcw size={16} aria-hidden="true" />{state.loading ? "Refreshing…" : "Refresh"}</button></div>
        {!state.loading && !visiblePeople.length ? <div className="people-empty"><Users size={32} aria-hidden="true" /><h3>No people match your filters.</h3><p>Try a different name, TPM code or agency, or reset your filters.</p><button className="people-button secondary" onClick={resetFilters}>Reset filters</button></div> : null}
        <div className="people-cards">
          {visiblePeople.map((person) => <article className="people-card" key={person.id} aria-labelledby={`person-${person.id}`}>
            <header className="people-card-header"><div className="people-identity"><h3 id={`person-${person.id}`}>{person.full_name}</h3><p><Building2 size={15} aria-hidden="true" />{person.agency_name}</p><div className="people-person-meta"><Badge active={person.is_active} /><span>{person.agent_type === "SUBAGENT" ? "Sub-agent" : "Main Agent"}</span><span>{person.tpm_codes?.length || 0} TPM codes</span></div></div><div className="people-actions">{canForAgency(user, person.agency, "can_edit") ? <button className="people-button secondary" disabled={actionsBlocked} onClick={(event) => openEditor("person", person, null, event)}><Edit3 size={16} aria-hidden="true" />Edit person</button> : null}{canForAgency(user, person.agency, "can_create") ? <button className="people-button primary" disabled={actionsBlocked} onClick={(event) => openEditor("code", person, null, event)}><Plus size={16} aria-hidden="true" />Add TPM Code</button> : null}</div></header>
            <ul className="people-code-list" aria-label={`TPM codes for ${person.full_name}`}>
              {person.visibleCodes.map((code) => <li className="people-code-row" key={code.id}><div className="people-code-identity"><span className="people-code-label">TPM code</span><strong>{code.code}</strong><Badge active={code.is_active} /></div><div className="people-actions" role="group" aria-label={`Actions for TPM code ${code.code}`}>{codeActions(user, person, code).map((action) => { const [Icon, label, style] = actionDetails[action]; return <button key={action} className={`people-button ${style}`} disabled={actionsBlocked} aria-label={`${label} TPM code ${code.code}`} onClick={(event) => action === "edit" || action === "reassign" ? openEditor(action === "edit" ? "code" : "reassign", person, code, event) : setCodeStatus(person, code)}><Icon size={16} aria-hidden="true" />{label}</button>; })}</div></li>)}
            </ul>
            {!person.visibleCodes.length ? <p className="people-no-codes">{person.tpm_codes?.length ? "No TPM codes match the current filters. Show inactive codes to see more." : "No TPM codes assigned yet."}</p> : null}
          </article>)}
        </div>
      </section>
    </div>
  );
}
