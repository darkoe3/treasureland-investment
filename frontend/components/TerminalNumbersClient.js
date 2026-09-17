"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiPath, clientDownload, clientRequest } from "../lib/client-api";
import { groupImportMessages, importRowGroup, canConfirmTerminalImport, changeTerminalDraft, terminalActions, terminalChoices, terminalPayload } from "../lib/terminal-operations";

const emptyDraft = { agency: "", person: "", sub_agent_number: "", terminal_number: "", is_active: true, reason: "", confirmed: false };
const unpack = (data) => data.results || data;

export default function TerminalNumbersClient({ user, agencies, uploadPage = false }) {
  const admin = user.role === "SUPER_ADMIN";
  const [terminals, setTerminals] = useState([]);
  const [people, setPeople] = useState([]);
  const [filters, setFilters] = useState({ agency: "", active: "", search: "" });
  const [editor, setEditor] = useState(null);
  const [draft, setDraft] = useState(emptyDraft);
  const [history, setHistory] = useState(null);
  const [uploadAgency, setUploadAgency] = useState("");
  const [file, setFile] = useState(null);
  const [batch, setBatch] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const [importMode, setImportMode] = useState("LINK_EXISTING");
  const [reason, setReason] = useState("");
  const [warningsAcknowledged, setWarningsAcknowledged] = useState(false);
  const [rowFilter, setRowFilter] = useState("All");
  const [currentTime, setCurrentTime] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  async function reload() {
    const [rows, owners] = await Promise.all([
      clientRequest(apiPath("/terminal-numbers/")), clientRequest(apiPath("/people/")),
    ]);
    setTerminals(unpack(rows)); setPeople(unpack(owners));
  }
  useEffect(() => { let cancelled = false;
    Promise.all([clientRequest(apiPath("/terminal-numbers/")), clientRequest(apiPath("/people/"))])
      .then(([rows, owners]) => { if (!cancelled) { setTerminals(unpack(rows)); setPeople(unpack(owners)); } })
      .catch((failure) => { if (!cancelled) setError(failure.message); });
    return () => { cancelled = true; };
  }, []);

  async function run(work) {
    setPending(true); setError(""); setMessage("");
    try { await work(); } catch (failure) { setError(failure.message); } finally { setPending(false); }
  }
  const choices = terminalChoices(people, draft.agency, draft.person);
  const target = choices.people.find((person) => String(person.id) === String(draft.person));
  const targetAgency = agencies.find((agency) => String(agency.id) === String(draft.agency));
  const targetCode = choices.codes.find((code) => String(code.id) === String(draft.sub_agent_number));
  const visible = terminals.filter((row) => (!filters.agency || String(row.agency) === filters.agency) &&
    (!filters.active || String(row.is_active) === filters.active) &&
    [row.terminal_number, row.sub_agent_number_value, row.person_name, row.agency_name].join(" ").toLowerCase().includes(filters.search.toLowerCase()));

  function openEditor(mode, item = null) {
    setEditor({ mode, item }); setError("");
    setDraft(mode === "edit" ? { ...emptyDraft, ...item } : { ...emptyDraft });
  }
  function update(field, value) { setDraft((current) => changeTerminalDraft(current, field, value)); }
  async function save(event) {
    event.preventDefault();
    await run(async () => {
      const payload = terminalPayload(draft, editor.mode);
      const path = editor.mode === "add" ? "/terminal-numbers/" : `/terminal-numbers/${editor.item.id}/${editor.mode === "reassign" ? "reassign/" : ""}`;
      await clientRequest(apiPath(path), { method: editor.mode === "edit" ? "PATCH" : "POST", body: JSON.stringify(payload) });
      setEditor(null); await reload(); setMessage("Terminal saved. Historical transactions are preserved.");
    });
  }
  async function act(label, item) {
    if (label === "Edit" || label === "Reassign") { openEditor(label.toLowerCase(), item); return; }
    await run(async () => {
      if (label === "View history") {
        const events = await clientRequest(apiPath(`/terminal-numbers/${item.id}/history/`));
        setHistory({ item, events }); return;
      }
      if (!window.confirm(`${label} terminal ${item.terminal_number} for ${item.person_name} (${item.agency_name}), Sub-Agent Number ${item.sub_agent_number_value}?`)) return;
      await clientRequest(apiPath(`/terminal-numbers/${item.id}/${label.toLowerCase()}/`), { method: "POST", body: "{}" });
      await reload(); setMessage(`Terminal ${label === "Deactivate" ? "deactivated" : "reactivated"}.`);
    });
  }
  async function preview(event) {
    event.preventDefault();
    await run(async () => {
      const form = new FormData(); form.set("agency", uploadAgency); form.set("file", file); form.set("mode", importMode);
      const result = await clientRequest(apiPath("/terminal-number-imports/preview/"), { method: "POST", body: form });
      setBatch(result); setConfirmed(false); setWarningsAcknowledged(false); setReason("");
    });
  }
  async function batchAction(action) {
    await run(async () => {
      const result = await clientRequest(apiPath(`/terminal-number-imports/${batch.id}/${action}/`), { method: "POST", body: JSON.stringify({ confirmed, reason, warnings_acknowledged: warningsAcknowledged, acknowledged_counts: confirmed ? batch.preview_payload.creation_counts : null }) });
      setBatch(result); setConfirmed(false); setWarningsAcknowledged(false); setReason(""); await reload();
      setMessage(action === "confirm" ? `Import confirmed: ${result.result_counts.created} created, ${result.result_counts.unchanged} unchanged.` : "Import cancelled.");
    });
  }
  async function download() {
    await run(async () => {
      const result = await clientDownload(apiPath(`/terminal-number-imports/template/?agency=${uploadAgency}`));
      const url = URL.createObjectURL(result.blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = "terminal-register.xlsx"; anchor.click(); URL.revokeObjectURL(url);
    });
  }
  function downloadErrors() {
    const blob = new Blob([JSON.stringify({ agency: batch.agency, mode: batch.preview_payload.mode,
      errors: batch.errors, warnings: batch.warnings }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = "terminal-import-errors.json"; anchor.click(); URL.revokeObjectURL(url);
  }

  return <section className="terminal-register">
    <header className="terminal-heading"><div><h1>{uploadPage ? "Upload terminal register" : "Terminal Numbers"}</h1><p>Terminals belong to Sub-Agent Numbers, people and agencies.</p></div>
      <div className="terminal-actions">{admin && !uploadPage ? <><button onClick={() => openEditor("add")} disabled={pending}>Add terminal</button><Link href="/dashboard/terminal-numbers/upload">Upload Excel</Link></> : null}
        {uploadPage ? <Link href="/dashboard/terminal-numbers">Terminal Numbers</Link> : null}</div>
    </header>
    {error ? <p role="alert" className="error-message">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {editor ? <section className="panel" role="dialog" aria-modal="false" aria-labelledby="terminal-editor-title">
      <h2 id="terminal-editor-title">{editor.mode === "add" ? "Add terminal" : editor.mode === "edit" ? "Edit Terminal Number" : "Reassign terminal"}</h2>
      {editor.item ? <p>Current: {editor.item.terminal_number} · {editor.item.sub_agent_number_value} · {editor.item.person_name} · {editor.item.agency_name}</p> : null}
      <form onSubmit={save}><fieldset disabled={pending}>
        {editor.mode !== "edit" ? <div className="terminal-fields">
          <label>Agency<select required value={draft.agency} onChange={(event) => update("agency", event.target.value)}><option value="">Select Agency</option>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
          <label>Person<select required disabled={!draft.agency} value={draft.person} onChange={(event) => update("person", event.target.value)}><option value="">Select Person</option>{choices.people.map((person) => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label>
          <label>Sub-Agent Number<select required disabled={!draft.person} value={draft.sub_agent_number} onChange={(event) => update("sub_agent_number", event.target.value)}><option value="">Select Sub-Agent Number</option>{choices.codes.map((code) => <option key={code.id} value={code.id}>{code.code}</option>)}</select></label>
        </div> : null}
        {editor.mode !== "reassign" ? <label>Terminal Number<input required maxLength={80} value={draft.terminal_number} onChange={(event) => update("terminal_number", event.target.value)} /></label> : <>
          <p>From {editor.item.agency_name} / {editor.item.person_name} / {editor.item.sub_agent_number_value}<br />To {targetAgency?.name || "Select agency"} / {target?.full_name || "Select person"} / {targetCode?.code || "Select Sub-Agent Number"}</p>
          <label>Reason<textarea required maxLength={2000} value={draft.reason} onChange={(event) => update("reason", event.target.value)} /></label>
          <label className="terminal-check"><input type="checkbox" checked={draft.confirmed} onChange={(event) => setDraft({ ...draft, confirmed: event.target.checked })} />I confirm the displayed reassignment, including any change of agency. Historical transactions will retain their recorded identity.</label>
        </>}
        {editor.mode === "add" ? <label>Active status<select value={String(draft.is_active)} onChange={(event) => update("is_active", event.target.value === "true")}><option value="true">Active</option><option value="false">Inactive</option></select></label> : null}
        <div className="terminal-actions"><button type="submit" disabled={editor.mode === "reassign" && !draft.confirmed}>{editor.mode === "reassign" ? "Confirm reassignment" : "Save terminal"}</button><button type="button" onClick={() => setEditor(null)}>Cancel</button></div>
      </fieldset></form>
    </section> : null}
    {uploadPage && admin ? <section className="panel"><h2>Upload Excel</h2>
      <p>Columns A–D: S/NOS, SUB AGT NOS, TERMINAL NOS, NAME. Preview creates no terminal assignments. Resolve assignment conflicts through manual actions before uploading again.</p>
      <form onSubmit={preview}><fieldset disabled={pending || batch?.status === "PREVIEWED"}>
        <label>Agency<select required value={uploadAgency} onChange={(event) => setUploadAgency(event.target.value)}><option value="">Select Agency</option>{agencies.map((agency) => <option value={agency.id} key={agency.id}>{agency.name}</option>)}</select></label>
        <label>Import mode<select value={importMode} onChange={(event) => setImportMode(event.target.value)}><option value="LINK_EXISTING">LINK_EXISTING — link existing records</option><option value="ONBOARD_MISSING">ONBOARD_MISSING — create missing records</option></select></label>
        <p>{importMode === "ONBOARD_MISSING" ? "Super Admin onboarding may create missing People, Sub-Agent Numbers and Terminals. Preview makes no master-data changes. Confirmation requires a reason and acknowledgement of creation counts. Existing records are never renamed or reassigned." : "People and Sub-Agent Numbers must already exist. Only Terminal mappings are created."}</p>
        <button type="button" disabled={!uploadAgency} onClick={download}>Download template</button>
        <label>Excel workbook<input type="file" accept=".xlsx" required onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>
        <button disabled={!file || !uploadAgency} type="submit">Preview upload</button>
      </fieldset></form>
      {batch ? <section aria-labelledby="terminal-preview-title"><h2 id="terminal-preview-title">Import preview — {batch.status}</h2>
        <p>{batch.original_filename} · {agencies.find((agency) => agency.id === batch.agency)?.name} · Expires {new Date(batch.expires_at).toLocaleString()}</p>
        <p>Mode: {batch.preview_payload.mode || "LINK_EXISTING"}</p>
        <p>Ignored blank template rows: {batch.preview_payload.ignored_blank_rows ?? 0}. Rows with no Sub-Agent Number, Terminal Number or Name are ignored, even when S/NOS is filled.</p>
        {batch.errors?.length ? <button type="button" onClick={downloadErrors}>Download error results</button> : null}
        <dl>{Object.entries(batch.preview_payload.summary || {}).map(([category, count]) => <div key={category}><dt>{category}</dt><dd>{count}</dd></div>)}</dl>
        {[{ title: "Blocking errors", items: batch.errors }, { title: "Warnings", items: batch.warnings }].map(({ title, items }) => items?.length ? <div key={title} role={title === "Blocking errors" ? "alert" : undefined}><h3>{title}: {items.length}</h3>{groupImportMessages(items).map((group) => <details key={group.label}><summary>{group.label} ({group.rows.length} rows)</summary><ul>{group.rows.map((item, index) => <li key={index}>{item.message}</li>)}</ul></details>)}</div> : null)}
        <label>Preview filter<select value={rowFilter} onChange={(event) => setRowFilter(event.target.value)}>{["All", "New", "Unchanged", "Conflict", "Invalid"].map((filter) => <option key={filter}>{filter}</option>)}</select></label>
        <div className="terminal-table"><table><thead><tr><th>Row</th><th>Sub-Agent Number</th><th>Terminal Number</th><th>Name</th><th>Classification</th></tr></thead><tbody>{batch.preview_payload.rows.filter((row) => rowFilter === "All" || importRowGroup(row.classification) === rowFilter).map((row) => <tr key={row.row}><td>{row.row}</td><td>{row.sub_agent_number_value}</td><td>{row.terminal_number}</td><td>{row.name}</td><td>{row.classification}</td></tr>)}</tbody></table></div>
        {batch.status === "PREVIEWED" ? <div className="terminal-confirmation"><h3>Confirm import</h3><p>Only the displayed new records will be created. Unchanged rows will be skipped. The entire batch rolls back if any row fails.</p>
          <p>Selected agency: {agencies.find((agency) => agency.id === batch.agency)?.name}. Creation counts: {batch.preview_payload.creation_counts?.people || 0} People, {batch.preview_payload.creation_counts?.sub_agent_numbers || 0} Sub-Agent Numbers, {batch.preview_payload.creation_counts?.terminals || 0} Terminals.</p>
          {batch.preview_payload.mode === "ONBOARD_MISSING" ? <label>Onboarding reason<textarea required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></label> : null}
          {batch.warnings?.length ? <label className="terminal-check"><input type="checkbox" checked={warningsAcknowledged} onChange={(event) => setWarningsAcknowledged(event.target.checked)} />I verified the numeric identifiers against the original source values, including leading zeroes.</label> : null}
          <label className="terminal-check"><input type="checkbox" checked={confirmed} disabled={pending || Boolean(batch.errors.length)} onChange={(event) => setConfirmed(event.target.checked)} />I reviewed the selected agency, rows and warnings, acknowledge the displayed creation counts and confirm this import.</label>
          <div className="terminal-actions"><button disabled={pending || !canConfirmTerminalImport(batch, confirmed, currentTime, reason, warningsAcknowledged)} onClick={() => batchAction("confirm")}>Confirm import</button><button disabled={pending} onClick={() => batchAction("cancel")}>Cancel import</button><button disabled={pending} onClick={() => { setBatch(null); setConfirmed(false); }}>Start fresh preview</button></div>
        </div> : null}
      </section> : null}
    </section> : null}
    {!uploadPage ? <>
      <div className="terminal-fields"><label>Search<input type="search" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder="Terminal, Sub-Agent Number or person" /></label>
        <label>Agency filter<select value={filters.agency} onChange={(event) => setFilters({ ...filters, agency: event.target.value })}><option value="">All accessible agencies</option>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
        <label>Status<select value={filters.active} onChange={(event) => setFilters({ ...filters, active: event.target.value })}><option value="">Active and inactive</option><option value="true">Active</option><option value="false">Inactive</option></select></label>
      </div><p role="status">{visible.length} terminals</p>
      <div className="terminal-cards">{visible.map((item) => <article className="panel" key={item.id}><h2>{item.terminal_number}</h2><dl>
        <div><dt>Sub-Agent Number</dt><dd>{item.sub_agent_number_value}</dd></div><div><dt>Person</dt><dd>{item.person_name}</dd></div><div><dt>Agency</dt><dd>{item.agency_name}</dd></div><div><dt>Status</dt><dd>{item.is_active ? "Active" : "Inactive"}</dd></div><div><dt>Updated date</dt><dd>{new Date(item.updated_at).toLocaleString()}</dd></div>
      </dl><div className="terminal-actions">{terminalActions(user, item).map((label) => <button key={label} disabled={pending} onClick={() => act(label, item)}>{label}</button>)}</div></article>)}</div>
    </> : null}
    {history ? <section className="panel" aria-labelledby="terminal-history-title"><h2 id="terminal-history-title">Assignment history: {history.item.terminal_number}</h2><button onClick={() => setHistory(null)}>Close history</button>
      <ol>{history.events.map((event) => <li key={event.id}><strong>{event.action.replaceAll("_", " ")}</strong> · {new Date(event.created_at).toLocaleString()}<p>{event.user_email || "User"} · {event.description}</p>
        {event.old_values?.terminal_number ? <p>Previous: {event.old_values.terminal_number} · {event.old_values.sub_agent_number_value} · {event.old_values.person_name} · {event.old_values.agency_name} · {event.old_values.is_active ? "Active" : "Inactive"}</p> : null}
        <p>New: {event.new_values.terminal_number} · {event.new_values.sub_agent_number_value} · {event.new_values.person_name} · {event.new_values.agency_name} · {event.new_values.is_active ? "Active" : "Inactive"}</p>
      </li>)}</ol>
    </section> : null}
  </section>;
}
