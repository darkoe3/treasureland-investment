"use client";

import { AlertTriangle, CheckCircle2, FileSpreadsheet, Upload, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPath, clientRequest } from "../lib/client-api";
import { canForAgency, moneyText } from "../lib/phase4-operations";

const MAX_FILE_SIZE = 5 * 1024 * 1024;

function listMessages(items = []) {
  return items.map((item, index) => (
    <li key={`${item.cell || item.row || "message"}-${index}`}>
      {item.row ? `Row ${item.row}: ` : ""}{item.cell ? `${item.cell}: ` : ""}{item.message || String(item)}
    </li>
  ));
}

export default function DailySheetImportClient({ user, agencies = [] }) {
  const router = useRouter();
  const selectableAgencies = useMemo(
    () => user.role === "SUPER_ADMIN" ? agencies : agencies.filter((agency) => canForAgency(user, agency.id, "can_create")),
    [agencies, user],
  );
  const [form, setForm] = useState({ agency: "", transaction_date: new Date().toISOString().slice(0, 10), file: null });
  const [batch, setBatch] = useState(null);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [ackDateMismatch, setAckDateMismatch] = useState(false);
  const [state, setState] = useState({ loading: false, error: "", success: "" });

  function selectFile(event) {
    const file = event.target.files?.[0] || null;
    setBatch(null);
    if (file && (!file.name.toLowerCase().endsWith(".xlsx") || file.size > MAX_FILE_SIZE)) {
      setState({ loading: false, error: "Choose a .xlsx file no larger than 5 MB.", success: "" });
      setForm({ ...form, file: null });
      return;
    }
    setState({ loading: false, error: "", success: "" });
    setForm({ ...form, file });
  }

  async function preview(event) {
    event.preventDefault();
    if (!form.agency || !form.transaction_date || !form.file) {
      setState({ loading: false, error: "Select an agency, date and .xlsx file.", success: "" });
      return;
    }
    const body = new FormData();
    body.set("agency", form.agency);
    body.set("transaction_date", form.transaction_date);
    body.set("file", form.file);
    setState({ loading: true, error: "", success: "" });
    try {
      const payload = await clientRequest(apiPath("/daily-sheet-imports/preview/"), { method: "POST", body });
      setBatch(payload);
      setReplaceExisting(false);
      setAckDateMismatch(false);
      setState({ loading: false, error: "", success: "Preview ready." });
    } catch (error) {
      setBatch(error.payload || null);
      setState({ loading: false, error: error.payload ? JSON.stringify(error.payload) : error.message, success: "" });
    }
  }

  async function confirmImport() {
    if (!batch) return;
    setState({ loading: true, error: "", success: "" });
    try {
      const payload = await clientRequest(apiPath(`/daily-sheet-imports/${batch.id}/confirm/`), {
        method: "POST",
        body: JSON.stringify({ replace_existing: replaceExisting, acknowledge_date_mismatch: ackDateMismatch }),
      });
      setState({ loading: false, error: "", success: "Import confirmed." });
      router.push(`/dashboard/daily-sheets/${payload.daily_sheet}`);
    } catch (error) {
      setState({ loading: false, error: error.payload ? JSON.stringify(error.payload) : error.message, success: "" });
    }
  }

  async function cancelPreview() {
    if (!batch) return;
    await clientRequest(apiPath(`/daily-sheet-imports/${batch.id}/cancel/`), { method: "POST", body: JSON.stringify({}) });
    setBatch(null);
    setState({ loading: false, error: "", success: "Preview cancelled." });
  }

  const previewPayload = batch?.preview_payload || {};
  const hasErrors = Boolean(batch?.errors?.length);
  const needsReplace = Boolean(previewPayload.existing_transaction_count);
  const needsDateAck = Boolean(previewPayload.requires_date_mismatch_ack);
  const canConfirm = batch && !hasErrors && (!needsReplace || replaceExisting) && (!needsDateAck || ackDateMismatch);

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Upload Daily Sheet Excel</h2>
            <p className="empty-state">Preview raw game sales before writing transactions.</p>
          </div>
        </div>
        {state.error ? <p className="form-error">{state.error}</p> : null}
        {state.success ? <p className="form-success">{state.success}</p> : null}
      </section>

      <form className="panel form-panel import-form" onSubmit={preview}>
        <div className="field-grid">
          <label className="field-group">Agency
            <select required value={form.agency} onChange={(event) => setForm({ ...form, agency: event.target.value })}>
              <option value="">Select agency</option>
              {selectableAgencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}
            </select>
          </label>
          <label className="field-group">Transaction date
            <input type="date" required value={form.transaction_date} onChange={(event) => setForm({ ...form, transaction_date: event.target.value })} />
          </label>
          <label className="field-group">Workbook
            <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={selectFile} />
          </label>
        </div>
        <button className="primary-button" type="submit" disabled={state.loading}>
          <Upload size={16} aria-hidden="true" />
          {state.loading ? "Preparing..." : "Preview upload"}
        </button>
      </form>

      {batch ? (
        <>
          <section className="metric-grid import-metrics">
            <div className="metric-card"><FileSpreadsheet size={20} /><p>File</p><strong>{previewPayload.file_name}</strong></div>
            <div className="metric-card"><p>Valid rows</p><strong>{previewPayload.valid_row_count}</strong><p>{previewPayload.ignored_blank_rows} blank, {previewPayload.ignored_zero_rows} zero ignored</p></div>
            <div className="metric-card"><p>NET Sales</p><strong>{moneyText(previewPayload.sheet_totals?.net_sales)}</strong></div>
            <div className="metric-card"><p>To Pay</p><strong>{moneyText(previewPayload.sheet_totals?.to_pay)}</strong></div>
          </section>

          {batch.errors?.length ? <section className="panel"><h2>Blocking Errors</h2><ul className="message-list error-list">{listMessages(batch.errors)}</ul></section> : null}
          {batch.warnings?.length ? <section className="panel"><h2>Warnings</h2><ul className="message-list warning-list">{listMessages(batch.warnings)}</ul></section> : null}

          <section className="panel">
            <div className="panel-heading"><h2>Game Mapping</h2><span>{previewPayload.game_columns?.length || 0} columns</span></div>
            <div className="chip-wrap">
              {(previewPayload.game_columns || []).map((column) => <span className="mini-chip" key={column.letter}>{column.letter}: {column.header} to {column.game_name}</span>)}
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading"><h2>Row Preview</h2><span>{previewPayload.agency_name} / {previewPayload.transaction_date}</span></div>
            <p className="scroll-hint">Scroll the preview table horizontally to inspect game columns.</p>
            <div className="table-wrap summary-table-wrap import-preview-wrap" tabIndex="0" role="region" aria-label="Import preview rows with horizontal scrolling">
              <table className="summary-table import-preview-table">
                <thead>
                  <tr>
                    <th>Excel Row</th><th>SUB AGT NOS</th><th>TPM Code</th><th>System Name</th><th>Workbook Name</th>
                    {(previewPayload.game_columns || []).map((column) => <th key={column.letter}>{column.game_name}</th>)}
                    <th>NET Sales</th><th>To Pay</th>
                  </tr>
                </thead>
                <tbody>
                  {(previewPayload.rows || []).map((row) => (
                    <tr key={`${row.excel_row}-${row.tpm_code}`}>
                      <td>{row.excel_row}</td><td>{row.sub_agent_no}</td><td>{row.tpm_code}</td><td>{row.person_name}</td><td>{row.workbook_name || "Missing"}</td>
                      {(previewPayload.game_columns || []).map((column) => <td key={column.letter}>{moneyText(row.amounts?.[column.game_name])}</td>)}
                      <td>{moneyText(row.net_sales)}</td><td>{moneyText(row.to_pay)}</td>
                    </tr>
                  ))}
                  {!previewPayload.rows?.length ? <tr><td colSpan="8" className="empty-cell">No importable rows.</td></tr> : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            {needsReplace ? (
              <label className="switch-row strong">
                <input type="checkbox" checked={replaceExisting} onChange={(event) => setReplaceExisting(event.target.checked)} />
                Replace {previewPayload.existing_transaction_count} existing transaction rows
              </label>
            ) : null}
            {needsDateAck ? (
              <label className="switch-row strong">
                <input type="checkbox" checked={ackDateMismatch} onChange={(event) => setAckDateMismatch(event.target.checked)} />
                Import using selected date despite workbook date mismatch
              </label>
            ) : null}
            <div className="button-row">
              <button className="primary-button" type="button" disabled={!canConfirm || state.loading} onClick={confirmImport}><CheckCircle2 size={16} />Confirm Import</button>
              <button className="danger-button" type="button" disabled={state.loading} onClick={cancelPreview}><XCircle size={16} />Cancel Preview</button>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
