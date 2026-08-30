"use client";

import Link from "next/link";
import { CheckCircle2, RotateCcw, Save, Send, Undo2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import {
  actionAvailability,
  activeTpmOptions,
  buildTransactionPayload,
  calculateTransactionPreview,
  canForAgency,
  differenceLabel,
  listFromPayload,
  moneyText,
  searchPeople,
} from "../lib/phase4-operations";

function statusClass(value) {
  return (value || "empty").toLowerCase();
}

export default function DailySheetDetailClient({ user, initialSheet, initialPeople = [] }) {
  const [sheet, setSheet] = useState(initialSheet);
  const [people, setPeople] = useState(initialPeople);
  const [transactions, setTransactions] = useState([]);
  const [omissions, setOmissions] = useState([]);
  const [audits, setAudits] = useState([]);
  const [query, setQuery] = useState("");
  const [selectedTpm, setSelectedTpm] = useState("");
  const [gameSales, setGameSales] = useState({});
  const [manual, setManual] = useState({ incoming_funds: sheet.incoming_funds ?? "", tax: sheet.tax ?? "", reconciliation_note: sheet.reconciliation_note || "" });
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ error: "", success: "" });
  const [reason, setReason] = useState("");

  async function refreshAll() {
    const [sheetPayload, txnPayload, omissionPayload, peoplePayload, auditPayload] = await Promise.all([
      clientRequest(apiPath(`/daily-sheets/${sheet.id}/summary/`)),
      clientRequest(apiPath(`/tpm-daily-transactions/?daily_sheet=${sheet.id}`)),
      clientRequest(apiPath(`/omitted-terminals/?daily_sheet=${sheet.id}`)),
      clientRequest(apiPath(`/people/?agency=${sheet.agency}`)).catch(() => people),
      clientRequest(apiPath(`/audit-logs/?daily_sheet=${sheet.id}`)).catch(() => []),
    ]);
    setSheet(sheetPayload);
    setTransactions(listFromPayload(txnPayload));
    setOmissions(listFromPayload(omissionPayload));
    setAudits(listFromPayload(auditPayload));
    setPeople(listFromPayload(peoplePayload));
    setManual({ incoming_funds: sheetPayload.incoming_funds ?? "", tax: sheetPayload.tax ?? "", reconciliation_note: sheetPayload.reconciliation_note || "" });
    setDirty(false);
  }

  useEffect(() => {
    queueMicrotask(() => {
      refreshAll();
    });
    // Initial load only; successful mutations call refreshAll explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handler = (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const editable = ["DRAFT", "RETURNED", "REOPENED"].includes(sheet.status);
  const mayEdit = editable && canForAgency(user, sheet.agency, "can_edit");
  const mayCreate = editable && canForAgency(user, sheet.agency, "can_create");
  const mayDelete = editable && canForAgency(user, sheet.agency, "can_delete");
  const options = useMemo(() => activeTpmOptions(searchPeople(people, query)).filter((item) => Number(item.agency) === Number(sheet.agency)), [people, query, sheet.agency]);
  const selected = options.find((item) => Number(item.id) === Number(selectedTpm));
  const preview = calculateTransactionPreview(gameSales, selected?.agent_type === "SUBAGENT");
  const actions = actionAvailability(user, sheet);
  const activeOmissions = omissions.filter((item) => item.is_active !== false);
  const missingExpected = sheet.omitted_terminals?.items?.filter((item) => !item.reason) || [];

  function setSale(gameId, value) {
    setGameSales({ ...gameSales, [gameId]: value });
    setDirty(true);
  }

  async function guarded(operation) {
    setBusy(true);
    setMessage({ error: "", success: "" });
    try {
      const success = await operation();
      setMessage({ error: "", success: success || "Saved." });
      await refreshAll();
    } catch (error) {
      setMessage({ error: error.payload ? JSON.stringify(error.payload) : error.message, success: "" });
    } finally {
      setBusy(false);
    }
  }

  async function saveTransaction(event) {
    event.preventDefault();
    await guarded(async () => {
      await clientRequest(apiPath("/tpm-daily-transactions/"), {
        method: "POST",
        body: JSON.stringify(buildTransactionPayload(sheet.id, selectedTpm, sheet.sheet_games, gameSales)),
      });
      setSelectedTpm("");
      setGameSales({});
      setDirty(false);
      return "Transaction saved.";
    });
  }

  async function deleteTransaction(txn) {
    if (!window.confirm(`Remove ${txn.tpm_code_value} from this sheet?`)) return;
    await guarded(async () => {
      await clientRequest(apiPath(`/tpm-daily-transactions/${txn.id}/`), { method: "DELETE" });
      return "Transaction removed.";
    });
  }

  async function markOmitted(item) {
    const text = window.prompt(`Reason for omitting ${item.code}`);
    if (!text?.trim()) return;
    await guarded(async () => {
      await clientRequest(apiPath("/omitted-terminals/"), {
        method: "POST",
        body: JSON.stringify({ daily_sheet: sheet.id, tpm_code: item.tpm_code, reason: text.trim(), is_active: true }),
      });
      return "Terminal marked omitted.";
    });
  }

  async function removeOmission(item) {
    const record = activeOmissions.find((omission) => Number(omission.tpm_code) === Number(item.tpm_code));
    if (!record) return;
    await guarded(async () => {
      await clientRequest(apiPath(`/omitted-terminals/${record.id}/`), { method: "DELETE" });
      return "Omission removed.";
    });
  }

  async function saveManual(event) {
    event.preventDefault();
    await guarded(async () => {
      await clientRequest(apiPath(`/daily-sheets/${sheet.id}/`), {
        method: "PATCH",
        body: JSON.stringify({
          incoming_funds: manual.incoming_funds === "" ? null : Number(manual.incoming_funds).toFixed(2),
          tax: manual.tax === "" ? null : Number(manual.tax).toFixed(2),
          reconciliation_note: manual.reconciliation_note,
        }),
      });
      setDirty(false);
      return "Agency totals saved.";
    });
  }

  async function workflow(action) {
    const body = action === "return" ? { return_comment: reason } : action === "reopen" ? { reopen_reason: reason } : {};
    await guarded(async () => {
      await clientRequest(apiPath(`/daily-sheets/${sheet.id}/${action}/`), { method: "POST", body: JSON.stringify(body) });
      setReason("");
      return "Workflow action completed.";
    });
  }

  return (
    <div className="page-stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>{sheet.agency_name} - {sheet.transaction_date}</h2>
            <span className={`status-pill ${statusClass(sheet.status)}`}>{sheet.status}</span>
          </div>
          <Link className="text-link" href="/dashboard/daily-sheets">Back to sheets</Link>
        </div>
        {message.error ? <p className="form-error">{message.error}</p> : null}
        {message.success ? <p className="form-success">{message.success}</p> : null}
      </section>

      <section className="metric-grid">
        <div className="metric-card"><p>Total NET Sales</p><strong>{moneyText(sheet.gross_sales)}</strong></div>
        <div className="metric-card"><p>Total To Pay</p><strong>{moneyText(sheet.total_to_pay)}</strong></div>
        <div className="metric-card"><p>Difference</p><strong>{moneyText(sheet.variance)}</strong><p>{differenceLabel(sheet.variance)}</p></div>
        <div className="metric-card"><p>Terminals</p><strong>{sheet.entered_terminals}/{sheet.total_terminals}</strong><p>{sheet.omitted_terminals?.count || 0} omitted</p></div>
      </section>

      <section className="form-grid">
        <form className="panel form-panel" onSubmit={saveTransaction}>
          <div className="panel-heading"><h2>Transaction Entry</h2></div>
          <label className="field-group">Search Name or TPM Code
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Type a person name or TPM code" disabled={!mayCreate} />
          </label>
          <label className="field-group">Terminal
            <select required value={selectedTpm} onChange={(event) => setSelectedTpm(event.target.value)} disabled={!mayCreate}>
              <option value="">Select TPM code</option>
              {options.map((item) => <option key={item.id} value={item.id}>{item.person_name} - {item.code}</option>)}
            </select>
          </label>
          {selected ? <p className="empty-state">{selected.person_name} / {selected.code} / {selected.agent_type === "SUBAGENT" ? "Sub-agent" : "Main Agent"}</p> : null}
          <div className="field-grid">
            {sheet.sheet_games.map((game) => (
              <label className="field-group" key={game.id}>{game.game_name_snapshot}
                <input type="number" step="0.01" min="0" value={gameSales[game.id] || ""} onChange={(event) => setSale(game.id, event.target.value)} disabled={!mayCreate} />
              </label>
            ))}
          </div>
          <div className="summary-strip">
            <span>NET {moneyText(preview.netSales)}</span>
            <span>To Pay {moneyText(preview.toPay)}</span>
            <span>Sub-agent {moneyText(preview.subagentShare)}</span>
            <span>Organisation {moneyText(preview.organisationShare)}</span>
          </div>
          <button className="primary-button" type="submit" disabled={!mayCreate || !selectedTpm || busy}><Save size={16} />Save row</button>
        </form>

        <form className="panel form-panel" onSubmit={saveManual}>
          <div className="panel-heading"><h2>Agency Daily Total</h2></div>
          <label className="field-group">Manual tax
            <input type="number" step="0.01" min="0" value={manual.tax} onChange={(event) => { setManual({ ...manual, tax: event.target.value }); setDirty(true); }} disabled={!mayEdit} />
          </label>
          <label className="field-group">Actual amount received
            <input type="number" step="0.01" min="0" value={manual.incoming_funds} onChange={(event) => { setManual({ ...manual, incoming_funds: event.target.value }); setDirty(true); }} disabled={!mayEdit} />
          </label>
          <label className="field-group">Reconciliation note
            <input value={manual.reconciliation_note} onChange={(event) => { setManual({ ...manual, reconciliation_note: event.target.value }); setDirty(true); }} disabled={!mayEdit} />
          </label>
          <button className="primary-button" type="submit" disabled={!mayEdit || busy}><Save size={16} />Save totals</button>
        </form>
      </section>

      <section className="panel">
        <div className="panel-heading"><h2>Daily Sheet Summary</h2><span>{transactions.length} transaction rows</span></div>
        <div className="table-wrap responsive-table wide-table">
          <table>
            <thead><tr><th>No</th><th>Name</th><th>TPM Code</th>{sheet.sheet_games.map((game) => <th key={game.id}>{game.game_name_snapshot}</th>)}<th>NET Sales</th><th>To Pay</th><th>Total</th><th></th></tr></thead>
            <tbody>
              {!transactions.length ? <tr><td colSpan={7 + sheet.sheet_games.length} className="empty-cell">No transactions entered yet.</td></tr> : null}
              {transactions.map((txn, index) => (
                <tr key={txn.id}>
                  <td data-label="No">{index + 1}</td>
                  <td data-label="Name">{txn.person_name_snapshot}</td>
                  <td data-label="TPM Code">{txn.tpm_code_value}</td>
                  {sheet.sheet_games.map((game) => {
                    const sale = txn.sales.find((item) => Number(item.daily_sheet_game) === Number(game.id));
                    return <td key={game.id} data-label={game.game_name_snapshot}>{moneyText(sale?.amount)}</td>;
                  })}
                  <td data-label="NET Sales">{moneyText(txn.net_sales)}</td>
                  <td data-label="To Pay">{moneyText(txn.to_pay)}</td>
                  <td data-label="Total">{moneyText(txn.to_pay)}</td>
                  <td data-label="Actions"><button className="danger-button" type="button" disabled={!mayDelete || busy} onClick={() => deleteTransaction(txn)}><XCircle size={16} />Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="content-grid">
        <div className="panel">
          <div className="panel-heading"><h2>Omitted & Missing Terminals</h2></div>
          <div className="list-stack">
            {(sheet.omitted_terminals?.items || []).map((item) => (
              <div className="list-row" key={item.tpm_code}>
                <span><strong>{item.code}</strong> {item.person_name}<br />{item.reason || "Missing entry or omission reason"}</span>
                {item.reason ? (
                  <button className="secondary-button" type="button" disabled={!mayEdit || busy} onClick={() => removeOmission(item)}><Undo2 size={16} />Undo</button>
                ) : (
                  <button className="primary-button" type="button" disabled={!mayEdit || busy} onClick={() => markOmitted(item)}><RotateCcw size={16} />Mark omitted</button>
                )}
              </div>
            ))}
            {!sheet.omitted_terminals?.items?.length ? <p className="empty-state">All active terminals have transactions.</p> : null}
          </div>
        </div>

        <div className="panel">
          <div className="panel-heading"><h2>Review Workflow</h2></div>
          <div className="summary-list">
            <span>Commission: <strong>{moneyText(sheet.commission)}</strong></span>
            <span>Sub-agent share: <strong>{moneyText(sheet.subagent_share)}</strong></span>
            <span>Organisation share: <strong>{moneyText(sheet.organisation_share_on_subagent_sales)}</strong></span>
            <span>Manual tax: <strong>{moneyText(sheet.manual_tax)}</strong></span>
            <span>Actual received: <strong>{moneyText(sheet.incoming_funds)}</strong></span>
          </div>
          <label className="field-group">Return or reopen reason
            <input value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
          <div className="button-row">
            <button className="primary-button" type="button" disabled={!actions.canSubmit || busy || missingExpected.length > 0} onClick={() => workflow("submit")}><Send size={16} />Submit</button>
            <button className="primary-button" type="button" disabled={!actions.canApprove || busy} onClick={() => workflow("approve")}><CheckCircle2 size={16} />Approve</button>
            <button className="danger-button" type="button" disabled={!actions.canReturn || busy || !reason.trim()} onClick={() => workflow("return")}><RotateCcw size={16} />Return</button>
            <button className="secondary-button" type="button" disabled={!actions.canReopen || busy || !reason.trim()} onClick={() => workflow("reopen")}><Undo2 size={16} />Reopen</button>
          </div>
        </div>
      </section>

      <section className="content-grid">
        <div className="panel">
          <div className="panel-heading"><h2>Grouped Person Totals</h2><span>{sheet.person_totals?.length || 0} people</span></div>
          <div className="table-wrap responsive-table">
            <table>
              <thead><tr><th>Name</th><th>NET Sales</th><th>To Pay</th></tr></thead>
              <tbody>
                {(sheet.person_totals || []).map((item) => (
                  <tr key={item.person}>
                    <td data-label="Name">{item.person_name}</td>
                    <td data-label="NET Sales">{moneyText(item.net_sales)}</td>
                    <td data-label="To Pay">{moneyText(item.to_pay)}</td>
                  </tr>
                ))}
                {!sheet.person_totals?.length ? <tr><td colSpan="3" className="empty-cell">No grouped totals yet.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-heading"><h2>Audit History</h2><span>{audits.length} entries</span></div>
          <div className="list-stack">
            {audits.slice(0, 8).map((item) => (
              <div className="list-row" key={item.id}>
                <span><strong>{item.action}</strong><br />{item.user_email} / {new Date(item.created_at).toLocaleString()}</span>
              </div>
            ))}
            {!audits.length ? <p className="empty-state">No permitted audit entries are available for this sheet.</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}
