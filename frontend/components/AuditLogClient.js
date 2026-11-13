"use client";
import { useEffect, useRef, useState } from "react";
import { apiPath, clientDownload, clientRequest } from "../lib/client-api";

const fields = [["search", "Search", "search"], ["date_from", "Date from", "date"], ["date_to", "Date to", "date"], ["user", "Actor ID", "number"], ["agency", "Agency ID", "number"], ["model_name", "Module / resource type", "text"], ["action", "Action code", "text"]];
export default function AuditLogClient() {
  const [filters, setFilters] = useState({});
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const dialog = useRef(null);
  const detailTrigger = useRef(null);
  useEffect(() => {
    let active = true;
    clientRequest(apiPath(`audit-logs/?${query}&page=${page}`)).then((result) => { if (active) setData(result); }).catch((err) => { if (active) setError(err.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [query, page]);
  useEffect(() => { if (detail) dialog.current?.showModal(); }, [detail]);
  function apply(next) {
    const value = new URLSearchParams(Object.entries(next).filter(([, v]) => v !== "")).toString();
    if (value !== query || page !== 1) { setBusy(true); setData(null); setError(""); setPage(1); setQuery(value); }
  }
  async function showDetail(row, target) {
    detailTrigger.current = target;
    try { setDetail(await clientRequest(apiPath(`audit-logs/${row.id}/`))); } catch (err) { setError(err.message); }
  }
  async function download() {
    setExporting(true); setError("");
    try {
      const { blob } = await clientDownload(apiPath(`audit-logs/export/?${query}`));
      const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = "audit-log.csv"; link.click(); URL.revokeObjectURL(url);
    } catch (err) { setError(err.message); } finally { setExporting(false); }
  }
  return <section className="audit-profile-page">
    <h2>Audit Log</h2><p>Organisation-wide activity, newest first. Results reflect recorded events; actor names and roles reflect current accounts.</p>
    <form className="audit-filter-grid" onSubmit={(event) => { event.preventDefault(); apply(filters); }}>
      {fields.map(([key, label, type]) => <label key={key}>{label}<input type={type} min={type === "number" ? 1 : undefined} value={filters[key] || ""} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })} /></label>)}
      <label>Role<select value={filters.role || ""} onChange={(e) => setFilters({ ...filters, role: e.target.value })}><option value="">All roles</option><option value="SUPER_ADMIN">Super Admin</option><option value="ACCOUNTANT">Accountant</option></select></label>
      <label>Result<select value={filters.result || ""} onChange={(e) => setFilters({ ...filters, result: e.target.value })}><option value="">All results</option><option value="SUCCESS">Success</option><option value="FAILED">Failed</option></select></label>
      <div className="audit-actions"><button className="primary-button" disabled={busy}>Apply filters</button><button type="button" className="secondary-button" onClick={() => { setFilters({}); apply({}); }}>Clear filters</button></div>
    </form>
    <div className="audit-actions"><button className="secondary-button" disabled={exporting || busy} onClick={download}>{exporting ? "Exporting…" : "Export CSV"}</button><span>Up to 10,000 events per export. Uses applied filters.</span></div>
    {error && <p role="alert">{error}</p>}
    {busy ? <p role="status">Loading audit events…</p> : data && <><p role="status">{data.count} events</p><div className="audit-table-scroll" tabIndex={0} role="region" aria-label="Audit events"><table><thead><tr>{["Date / time", "Actor", "Role", "Action", "Module", "Agency", "Reference", "Result", "Description", "Details"].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{data.results.map((row) => <tr key={row.id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.actor}</td><td>{row.actor_role.replaceAll("_", " ")}</td><td>{row.action_label}</td><td>{row.model_name}</td><td>{row.agency_name || "—"}</td><td>{row.object_id}</td><td>{row.result}</td><td>{row.description}</td><td><button className="secondary-button" onClick={(e) => showDetail(row, e.currentTarget)}>View details<span className="sr-only"> for event {row.id}</span></button></td></tr>)}</tbody></table>{!data.results.length && <p>No matching events.</p>}</div>
      <nav className="audit-actions" aria-label="Audit pagination"><button disabled={!data.previous} onClick={() => { setBusy(true); setData(null); setError(""); setPage(page - 1); }}>Previous</button><span>Page {page}</span><button disabled={!data.next} onClick={() => { setBusy(true); setData(null); setError(""); setPage(page + 1); }}>Next</button></nav></>}
    <dialog ref={dialog} className="audit-detail-dialog" aria-labelledby="audit-detail-title" onClose={() => { setDetail(null); detailTrigger.current?.focus(); }}>
      <h2 id="audit-detail-title">Event details</h2>{detail && <><dl>{[["Date / time", new Date(detail.created_at).toLocaleString()], ["Actor", detail.actor], ["Role", detail.actor_role], ["Action", detail.action_label], ["Agency", detail.agency_name || "—"], ["Resource", detail.model_name], ["Reference", detail.object_id], ["Result", detail.result]].map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><h3>Safe metadata</h3>{Object.entries(detail.metadata).map(([group, values]) => <section key={group}><h4>{group === "before" ? "Before" : "After"}</h4>{Object.keys(values).length ? <dl>{Object.entries(values).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value)}</dd></div>)}</dl> : <p>No safe metadata recorded.</p>}</section>)}</>}
      <button className="primary-button" onClick={() => dialog.current.close()}>Close</button>
    </dialog>
  </section>;
}
