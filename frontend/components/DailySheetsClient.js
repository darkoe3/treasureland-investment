"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { canForAgency, differenceLabel, listFromPayload, moneyText } from "../lib/phase4-operations";

function Status({ value }) {
  return <span className={`status-pill ${(value || "empty").toLowerCase()}`}>{value || "None"}</span>;
}

export default function DailySheetsClient({ user, initialAgencies = [] }) {
  const router = useRouter();
  const [sheets, setSheets] = useState([]);
  const [filters, setFilters] = useState({ agency: "", date: "", status: "" });
  const [form, setForm] = useState({ agency: "", transaction_date: new Date().toISOString().slice(0, 10) });
  const [state, setState] = useState({ loading: true, error: "", success: "" });

  async function loadSheets() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    const params = new URLSearchParams();
    if (filters.agency) params.set("agency", filters.agency);
    if (filters.date) params.set("date", filters.date);
    if (filters.status) params.set("status", filters.status);
    try {
      const payload = await clientRequest(apiPath(`/daily-sheets/${params.toString() ? `?${params}` : ""}`));
      setSheets(listFromPayload(payload));
      setState((current) => ({ ...current, loading: false }));
    } catch (error) {
      setState({ loading: false, error: error.message, success: "" });
    }
  }

  useEffect(() => {
    queueMicrotask(() => {
      loadSheets();
    });
    // Initial load only; filters are applied explicitly by the user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createAgencies = useMemo(() => initialAgencies.filter((agency) => canForAgency(user, agency.id, "can_create")), [initialAgencies, user]);

  async function createSheet(event) {
    event.preventDefault();
    try {
      const payload = await clientRequest(apiPath("/daily-sheets/"), {
        method: "POST",
        body: JSON.stringify({ agency: Number(form.agency), transaction_date: form.transaction_date, incoming_funds: null, tax: null }),
      });
      setState({ loading: false, error: "", success: "Daily sheet created." });
      await loadSheets();
      router.push(`/dashboard/daily-sheets/${payload.id}`);
    } catch (error) {
      const detail = JSON.stringify(error.payload || {});
      setState({ loading: false, error: detail.includes("unique") ? "A daily sheet already exists for that agency and date." : error.message, success: "" });
    }
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <form className="toolbar" onSubmit={(event) => { event.preventDefault(); loadSheets(); }}>
          <label className="search-box">
            <Search size={18} aria-hidden="true" />
            <input type="date" value={filters.date} onChange={(event) => setFilters({ ...filters, date: event.target.value })} aria-label="Filter date" />
          </label>
          <select value={filters.agency} onChange={(event) => setFilters({ ...filters, agency: event.target.value })} aria-label="Filter agency">
            <option value="">All accessible agencies</option>
            {initialAgencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
          </select>
          <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} aria-label="Filter status">
            <option value="">Any status</option>
            {["DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "REOPENED"].map((status) => <option key={status}>{status}</option>)}
          </select>
          <button className="secondary-button" type="submit">Apply</button>
          <Link className="primary-button" href="/dashboard/daily-sheets/import"><Plus size={16} />Upload Excel</Link>
        </form>
      </section>

      <section className="form-grid">
        <form className="panel form-panel" onSubmit={createSheet}>
          <div className="panel-heading"><h2>Create Daily Sheet</h2></div>
          <div className="field-grid">
            <label className="field-group">Agency
              <select required value={form.agency} onChange={(event) => setForm({ ...form, agency: event.target.value })}>
                <option value="">Select agency</option>
                {createAgencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
              </select>
            </label>
            <label className="field-group">Date
              <input type="date" required value={form.transaction_date} onChange={(event) => setForm({ ...form, transaction_date: event.target.value })} />
            </label>
          </div>
          <button className="primary-button" type="submit"><Plus size={16} />Create sheet</button>
        </form>

        <div className="panel">
          <div className="panel-heading"><h2>Operational Rule</h2></div>
          <p className="empty-state">One active agency sheet is allowed per date. Games are copied into the sheet at creation and remain historical snapshots.</p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Daily Sheets</h2><span>{sheets.length} sheets</span></div>
        {state.error ? <p className="form-error">{state.error}</p> : null}
        {state.success ? <p className="form-success">{state.success}</p> : null}
        <div className="table-wrap responsive-table">
          <table>
            <thead><tr><th>Date</th><th>Agency</th><th>Status</th><th>Entered</th><th>NET Sales</th><th>To Pay</th><th>Difference</th><th></th></tr></thead>
            <tbody>
              {state.loading ? <tr><td colSpan="8" className="empty-cell">Loading daily sheets...</td></tr> : null}
              {!state.loading && !sheets.length ? <tr><td colSpan="8" className="empty-cell">No daily sheets match your filters.</td></tr> : null}
              {sheets.map((sheet) => (
                <tr key={sheet.id}>
                  <td data-label="Date">{sheet.transaction_date}</td>
                  <td data-label="Agency">{sheet.agency_name}</td>
                  <td data-label="Status"><Status value={sheet.status} /></td>
                  <td data-label="Entered">{sheet.entered_terminals}</td>
                  <td data-label="NET Sales">{moneyText(sheet.gross_sales)}</td>
                  <td data-label="To Pay">{moneyText(sheet.total_to_pay)}</td>
                  <td data-label="Difference">{moneyText(sheet.variance)}<br /><small>{differenceLabel(sheet.variance)}</small></td>
                  <td data-label="Open"><Link className="text-link" href={`/dashboard/daily-sheets/${sheet.id}`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
