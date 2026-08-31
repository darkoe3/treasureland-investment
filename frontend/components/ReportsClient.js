"use client";

import { Download, FileSpreadsheet, RotateCcw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { apiPath, clientDownload, clientRequest } from "../lib/client-api";
import {
  REPORT_STATUSES,
  buildReportQuery,
  differenceClass,
  filenameFromDisposition,
  moneyText,
  monthFromDate,
  resolvePeriodDisplay,
  todayISO,
  validateReportFilters,
  yearFromDate,
} from "../lib/report-operations";

const statusLabels = {
  APPROVED: "Approved",
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  RETURNED: "Returned",
  REOPENED: "Reopened",
};

const summaryLabels = {
  daily_sheet_count: "Daily sheets",
  transaction_row_count: "Transaction rows",
  distinct_people_count: "People",
  distinct_tpm_code_count: "TPM Codes",
  total_net_sales: "NET Sales",
  total_commission: "Commission 5%",
  total_to_pay: "To Pay",
  total_subagent_share: "Sub-agent share",
  total_organisation_share: "Organisation share",
  total_manual_tax: "Manual tax",
  total_actual_amount_received: "Actual received",
  total_difference: "Difference",
  total_omitted_terminals: "Omitted terminals",
};

function initialFilters() {
  const today = todayISO();
  return {
    agency: "",
    period: "daily",
    date: today,
    month: monthFromDate(today),
    year: yearFromDate(today),
    startDate: today,
    endDate: today,
    statuses: ["APPROVED"],
  };
}

function StatusControls({ filters, setFilters }) {
  function toggle(status) {
    const next = filters.statuses.includes(status)
      ? filters.statuses.filter((item) => item !== status)
      : [...filters.statuses, status];
    setFilters({ ...filters, statuses: next });
  }
  return (
    <div className="status-filter-grid" aria-label="Selected statuses">
      {REPORT_STATUSES.map((status) => (
        <label className="switch-row" key={status}>
          <input type="checkbox" checked={filters.statuses.includes(status)} onChange={() => toggle(status)} />
          {statusLabels[status]}
        </label>
      ))}
    </div>
  );
}

function PeriodControls({ filters, setFilters }) {
  if (filters.period === "monthly") {
    return (
      <div className="field-grid">
        <label className="field-group">Month
          <select value={filters.month} onChange={(event) => setFilters({ ...filters, month: event.target.value })}>
            {Array.from({ length: 12 }, (_, index) => String(index + 1).padStart(2, "0")).map((month) => <option key={month} value={month}>{month}</option>)}
          </select>
        </label>
        <label className="field-group">Year
          <input value={filters.year} inputMode="numeric" onChange={(event) => setFilters({ ...filters, year: event.target.value })} />
        </label>
      </div>
    );
  }
  if (filters.period === "custom") {
    return (
      <div className="field-grid">
        <label className="field-group">Start date
          <input type="date" value={filters.startDate} onChange={(event) => setFilters({ ...filters, startDate: event.target.value })} />
        </label>
        <label className="field-group">End date
          <input type="date" value={filters.endDate} onChange={(event) => setFilters({ ...filters, endDate: event.target.value })} />
        </label>
      </div>
    );
  }
  return (
    <label className="field-group">{filters.period === "weekly" ? "Date within week" : "Report date"}
      <input type="date" value={filters.date} onChange={(event) => setFilters({ ...filters, date: event.target.value })} />
    </label>
  );
}

export default function ReportsClient({ agencies = [] }) {
  const [filters, setFilters] = useState(initialFilters);
  const [report, setReport] = useState(null);
  const [state, setState] = useState({ loading: false, error: "", success: "" });
  const period = useMemo(() => resolvePeriodDisplay(filters), [filters]);
  const validation = validateReportFilters(filters);
  const operational = filters.statuses.some((status) => status !== "APPROVED");

  async function generate(event) {
    event.preventDefault();
    setState({ loading: true, error: "", success: "" });
    try {
      const query = buildReportQuery(filters);
      const payload = await clientRequest(apiPath(`/reports/agency-summary/?${query}`));
      setReport(payload);
      setState({ loading: false, error: "", success: "Report generated." });
    } catch (error) {
      setState({ loading: false, error: error.payload ? JSON.stringify(error.payload) : error.message, success: "" });
    }
  }

  async function download() {
    setState({ loading: true, error: "", success: "" });
    try {
      const query = buildReportQuery(filters);
      const result = await clientDownload(apiPath(`/reports/agency-summary/export/?${query}`));
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filenameFromDisposition(result.contentDisposition);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setState({ loading: false, error: "", success: "Excel report downloaded." });
    } catch (error) {
      setState({ loading: false, error: error.payload ? JSON.stringify(error.payload) : error.message, success: "" });
    }
  }

  function reset() {
    setFilters(initialFilters());
    setReport(null);
    setState({ loading: false, error: "", success: "" });
  }

  return (
    <div className="page-stack reports-page">
      <section className="panel">
        <form className="report-filters" onSubmit={generate}>
          <div className="field-grid">
            <label className="field-group">Agency
              <select value={filters.agency} onChange={(event) => setFilters({ ...filters, agency: event.target.value })}>
                <option value="">Select agency</option>
                {agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
              </select>
            </label>
            <label className="field-group">Report type
              <select value={filters.period} onChange={(event) => setFilters({ ...filters, period: event.target.value })}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="custom">Custom range</option>
              </select>
            </label>
          </div>
          <PeriodControls filters={filters} setFilters={setFilters} />
          <div className="report-period-strip">
            <span>Resolved start: <strong>{period.start || "Select dates"}</strong></span>
            <span>Resolved end: <strong>{period.end || "Select dates"}</strong></span>
          </div>
          <StatusControls filters={filters} setFilters={setFilters} />
          {operational ? <p className="form-error">Operational/non-final report: non-approved statuses are included.</p> : null}
          {validation ? <p className="empty-state">{validation}</p> : null}
          <div className="button-row compact">
            <button className="primary-button" type="submit" disabled={state.loading || Boolean(validation)}><Search size={16} />Generate report</button>
            <button className="secondary-button" type="button" onClick={reset}><RotateCcw size={16} />Reset filters</button>
            <button className="secondary-button" type="button" disabled={state.loading || Boolean(validation)} onClick={download}><Download size={16} />Download Excel</button>
          </div>
        </form>
      </section>

      {state.error ? <p className="form-error">{state.error}</p> : null}
      {state.success ? <p className="form-success">{state.success}</p> : null}
      {state.loading ? <section className="panel"><p className="empty-state">Loading report...</p></section> : null}
      {!state.loading && !report ? <section className="panel"><p className="empty-state">Choose an agency and generate a report preview.</p></section> : null}

      {report ? (
        <>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>{report.header.organisation}</h2>
                <p className="empty-state">{report.header.agency} / {report.header.report_type} / {report.header.start_date} to {report.header.end_date}</p>
              </div>
              <span className={`status-pill ${report.header.is_final ? "approved" : "draft"}`}>{report.header.label}</span>
            </div>
            <p className="empty-state">Statuses: {report.header.selected_status_labels.join(", ")} / Generated by {report.header.generated_by}</p>
          </section>

          <section className="metric-grid report-metrics">
            {Object.entries(summaryLabels).map(([key, label]) => (
              <div className="metric-card" key={key}>
                <p>{label}</p>
                <strong className={key === "total_difference" ? `difference-${differenceClass(report.summary[key])}` : ""}>
                  {key.includes("count") || key === "total_omitted_terminals" ? report.summary[key] : moneyText(report.summary[key])}
                </strong>
              </div>
            ))}
          </section>

          <section className="panel">
            <div className="panel-heading"><h2>Daily Reconciliation</h2><span>{report.daily_reconciliation.length} sheets</span></div>
            <div className="table-wrap responsive-table">
              <table>
                <thead><tr><th>Date</th><th>Status</th><th>NET Sales</th><th>Commission</th><th>To Pay</th><th>Tax</th><th>Actual received</th><th>Difference</th><th>Rows</th><th>Omitted</th></tr></thead>
                <tbody>
                  {!report.daily_reconciliation.length ? <tr><td colSpan="10" className="empty-cell">No daily sheets match this report.</td></tr> : null}
                  {report.daily_reconciliation.map((row) => (
                    <tr key={`${row.date}-${row.status}`}>
                      <td data-label="Date">{row.date}</td>
                      <td data-label="Status">{row.status}</td>
                      <td data-label="NET Sales">{moneyText(row.net_sales)}</td>
                      <td data-label="Commission">{moneyText(row.commission)}</td>
                      <td data-label="To Pay">{moneyText(row.to_pay)}</td>
                      <td data-label="Tax">{moneyText(row.tax)}</td>
                      <td data-label="Actual received">{moneyText(row.actual_amount_received)}</td>
                      <td data-label="Difference"><span className={`difference-${differenceClass(row.difference)}`}>{moneyText(row.difference)}</span></td>
                      <td data-label="Rows">{row.transaction_count}</td>
                      <td data-label="Omitted">{row.omitted_terminal_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading"><h2>Detailed TPM/Game Summary</h2><span>{report.details.length} TPM rows</span></div>
            <p className="scroll-hint">Scroll the detail table horizontally to view all game columns.</p>
            <div className="table-wrap summary-table-wrap" tabIndex="0" role="region" aria-label="Detailed report table with horizontal scrolling">
              <table className="summary-table" style={{ minWidth: `max(980px, ${520 + report.game_columns.length * 132}px)` }}>
                <thead><tr><th>No</th><th>Name</th><th>TPM Code</th>{report.game_columns.map((game) => <th key={game.key}>{game.name}</th>)}<th>NET Sales</th><th>To Pay</th><th>Total</th></tr></thead>
                <tbody>
                  {!report.details.length ? <tr><td colSpan={6 + report.game_columns.length} className="empty-cell">No transaction rows match this report.</td></tr> : null}
                  {report.details.map((row) => (
                    <tr key={`${row.person}-${row.tpm_code}`}>
                      <td>{row.no}</td>
                      <td>{row.name}</td>
                      <td>{row.tpm_code}</td>
                      {report.game_columns.map((game) => <td key={game.key}>{moneyText(row.games[game.key])}</td>)}
                      <td>{moneyText(row.net_sales)}</td>
                      <td>{moneyText(row.to_pay)}</td>
                      <td>{row.total === "" ? "" : moneyText(row.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
