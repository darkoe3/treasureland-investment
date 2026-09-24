"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiPath, clientRequest } from "../lib/client-api";
import { agencyConfirmationReady, canManageAgencies, filterAgencies } from "../lib/agency-operations";

const labels = { assigned_accountants: "Assigned accountants", people: "People", sub_agent_numbers: "Sub-Agent Numbers", terminal_numbers: "Terminal Numbers", daily_sheets: "Historical daily sheets", active_people: "Active people", active_sub_agent_numbers: "Active Sub-Agent Numbers", active_terminal_numbers: "Active Terminal Numbers", editable_daily_sheets: "Editable daily sheets" };
const basicCounts = ["assigned_accountants", "people", "sub_agent_numbers", "terminal_numbers", "daily_sheets"];
const impactCounts = ["assigned_accountants", "active_people", "active_sub_agent_numbers", "active_terminal_numbers", "editable_daily_sheets", "daily_sheets"];
const emptyDraft = { name: "", code: "", is_active: true, reason: "", confirmed: false, acknowledge_editable_sheets: false, confirm_code_change: false };
function Counts({ counts, fields = basicCounts }) {
  return <dl className="agency-counts">{fields.map((key) => <div key={key}><dt>{labels[key]}</dt><dd>{counts?.[key] ?? 0}</dd></div>)}</dl>;
}

export default function AgenciesClient({ user }) {
  const admin = canManageAgencies(user);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [editor, setEditor] = useState(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [fields, setFields] = useState({});
  const [pending, setPending] = useState(false);
  const [detail, setDetail] = useState(null);
  const dialog = useRef(null);
  async function load() {
    const result = await clientRequest(apiPath("agencies/"));
    // The backend uses unpaginated collections; reject incomplete results safely.
    if (result.next) throw new Error("Agency list is incomplete. Please contact your administrator.");
    setRows(result.results || result);
  }
  useEffect(() => {
    let cancelled = false;
    clientRequest(apiPath("agencies/")).then((result) => {
      if (result.next) throw new Error("Incomplete agency list");
      if (!cancelled) setRows(result.results || result);
    }).catch(() => { if (!cancelled) setError("Could not load agencies. Please retry."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => { if (editor) dialog.current?.showModal(); }, [editor]);
  async function open(mode, row) {
    setError(""); setFields({}); setMessage("");
    setDraft({ ...emptyDraft, ...(row ? { name: row.name, code: row.code, is_active: row.is_active } : {}) });
    if (mode === "deactivate") {
      setPending(true);
      try { const impact = await clientRequest(apiPath(`agencies/${row.id}/impact/`)); setEditor({ mode, row, impact }); }
      catch { setError("Could not load agency impact. Please retry."); }
      finally { setPending(false); }
    } else setEditor({ mode, row });
  }
  function close() { dialog.current?.close(); setEditor(null); setFields({}); }
  function change(key, value) { setDraft((current) => ({ ...current, [key]: value, ...(key === "code" ? { confirm_code_change: false } : {}) })); }
  const ready = editor && agencyConfirmationReady(editor.mode, { ...draft, codeChanged: draft.code.trim() !== editor.row?.code }, editor.impact);
  async function save(event) {
    event.preventDefault(); if (!admin || !ready || pending) return;
    setPending(true); setFields({});
    const { mode, row } = editor;
    const payload = mode === "create" ? { name: draft.name, code: draft.code, is_active: draft.is_active } : mode === "edit" ? { name: draft.name, code: draft.code, confirm_code_change: draft.confirm_code_change } : { reason: draft.reason, confirmed: draft.confirmed, acknowledge_editable_sheets: draft.acknowledge_editable_sheets };
    try {
      const updated = await clientRequest(apiPath(mode === "create" ? "agencies/" : `agencies/${row.id}/${mode === "edit" ? "" : `${mode}/`}`), { method: mode === "edit" ? "PATCH" : "POST", body: JSON.stringify(payload) });
      setRows((current) => mode === "create" ? [...current, updated] : current.map((item) => item.id === updated.id ? updated : item));
      setDetail(null); close(); setMessage(`Agency ${mode === "create" ? "created" : mode === "edit" ? "updated" : mode === "deactivate" ? "deactivated" : "reactivated"}.`);
    } catch (failure) { setFields(failure.status < 500 && failure.payload ? failure.payload : { detail: "Could not save the agency. Please retry." }); }
    finally { setPending(false); }
  }
  async function showDetail(row) {
    setPending(true); setError("");
    try { setDetail(await clientRequest(apiPath(`agencies/${row.id}/`))); }
    catch { setError("Could not load agency details. Please retry."); }
    finally { setPending(false); }
  }
  const fieldError = (key) => fields[key] ? <span className="agency-error" role="alert">{[].concat(fields[key]).join(" ")}</span> : null;
  const visible = filterAgencies(rows, search, active);
  return <section className="terminal-register agency-management">
    <header className="terminal-heading"><div><h1>Agencies</h1><p>Manage agencies and review their records and activity.</p></div>{admin && <button disabled={pending} onClick={() => open("create")}>Add Agency</button>}</header>
    {error && <p role="alert" className="agency-error">{error} <button onClick={() => { setLoading(true); setError(""); load().catch(() => setError("Could not load agencies. Please retry.")).finally(() => setLoading(false)); }}>Retry</button></p>}
    {message && <p role="status">{message}</p>}
    <div className="terminal-fields panel"><label>Search name or code<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></label><label>Status<select value={active} onChange={(event) => setActive(event.target.value)}><option value="">All agencies</option><option value="true">Active</option><option value="false">Inactive</option></select></label></div>
    {loading ? <p role="status">Loading agencies…</p> : !error && !visible.length ? <p>No agencies match your search and status filter.</p> : null}
    <div className="terminal-cards">{visible.map((row) => <article className="panel" key={row.id}><h2>{row.name}</h2><p>{row.code} · <span className={`agency-badge ${row.is_active ? "active" : "inactive"}`}>{row.is_active ? "Active" : "Inactive"}</span></p><Counts counts={row.counts} />{row.created_at && <p>Created {new Date(row.created_at).toLocaleDateString()}</p>}<div className="terminal-actions"><button disabled={pending} onClick={() => showDetail(row)}>View details</button>{admin && <><button disabled={pending} onClick={() => open("edit", row)}>Edit</button><button disabled={pending} onClick={() => open(row.is_active ? "deactivate" : "reactivate", row)}>{row.is_active ? "Deactivate" : "Reactivate"}</button></>}</div></article>)}</div>
    {detail && <section className="panel" aria-label="Agency details"><div className="terminal-heading"><h2>{detail.name} · {detail.code}</h2><button onClick={() => setDetail(null)}>Close details</button></div><p>{detail.is_active ? "Active" : "Inactive"}</p><Counts counts={detail.counts} fields={Object.keys(labels)} /><h3>Assigned accountants</h3>{detail.assigned_accountants.length ? <ul>{detail.assigned_accountants.map((item) => <li key={item.user_id}>{item.user__full_name}</li>)}</ul> : <p>No assigned accountants.</p>}<h3>Recent daily sheets</h3>{detail.recent_daily_sheets.length ? <ul>{detail.recent_daily_sheets.map((sheet) => <li key={sheet.id}><Link href={`/dashboard/daily-sheets/${sheet.id}`}>{sheet.transaction_date}</Link> · {sheet.status}</li>)}</ul> : <p>No daily sheets.</p>}<h3>Recent audit events</h3>{detail.recent_audit_events.length ? <ul>{detail.recent_audit_events.map((item) => <li key={item.id}>{item.action.replaceAll("_", " ")} · {new Date(item.created_at).toLocaleString()}</li>)}</ul> : <p>No audit events.</p>}</section>}
    {admin && <dialog ref={dialog} className="sheet-safety-dialog" onCancel={(event) => { if (pending) event.preventDefault(); else close(); }} aria-labelledby="agency-dialog-title">{editor && <form onSubmit={save}><fieldset disabled={pending}><h2 id="agency-dialog-title">{({ create: "Add Agency", edit: "Edit agency", deactivate: "Deactivate agency", reactivate: "Reactivate agency" })[editor.mode]}</h2>{["create", "edit"].includes(editor.mode) ? <><label>Agency name<input required maxLength={120} value={draft.name} onChange={(event) => change("name", event.target.value)} />{fieldError("name")}</label><label>Agency code<input required maxLength={40} pattern="[A-Za-z0-9_\-]+" value={draft.code} onChange={(event) => change("code", event.target.value)} />{fieldError("code")}</label><p>Use 1–40 ASCII letters, digits, underscores or hyphens.</p>{editor.mode === "create" ? <label className="terminal-check"><input type="checkbox" checked={draft.is_active} onChange={(event) => change("is_active", event.target.checked)} />Active</label> : <><p>The new name/code applies to future displays. Existing historical snapshots remain unchanged. Use Deactivate or Reactivate to change status.</p>{draft.code.trim() !== editor.row.code && <label className="terminal-check"><input type="checkbox" checked={draft.confirm_code_change} onChange={(event) => change("confirm_code_change", event.target.checked)} />I confirm the agency code change.</label>}{fieldError("confirm_code_change")}</>}</> : <><p>{editor.row.name} ({editor.row.code})</p>{editor.mode === "deactivate" ? <><Counts counts={editor.impact} fields={impactCounts} /><p>New sheets, imports, people, Sub-Agent Numbers, Terminal Numbers and accountant assignments will be blocked. Historical records and reports remain available.</p>{editor.impact.editable_daily_sheets > 0 && <label className="terminal-check"><input type="checkbox" checked={draft.acknowledge_editable_sheets} onChange={(event) => change("acknowledge_editable_sheets", event.target.checked)} />I acknowledge that Draft, Returned or Reopened sheets exist. They will remain preserved and cannot be edited while the agency is inactive.</label>}{fieldError("acknowledge_editable_sheets")}</> : <p>Related people, Sub-Agent Numbers, Terminal Numbers and accountant permissions retain their individual states.</p>}<label>Reason (required)<textarea required maxLength={1000} value={draft.reason} onChange={(event) => change("reason", event.target.value)} />{fieldError("reason")}</label><label className="terminal-check"><input type="checkbox" checked={draft.confirmed} onChange={(event) => change("confirmed", event.target.checked)} />I confirm {editor.mode === "deactivate" ? "deactivation" : "reactivation"} of this agency.</label>{fieldError("confirmed")}</>}{fieldError("detail")}{fieldError("non_field_errors")}{fieldError("is_active")}<div className="terminal-actions"><button type="button" onClick={close}>Cancel</button><button type="submit" disabled={!ready || pending}>{pending ? "Saving…" : "Confirm and save"}</button></div></fieldset></form>}</dialog>}
  </section>;
}
