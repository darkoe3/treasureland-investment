"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { formatPaymentMoney, paymentList } from "../lib/payment-operations";

function safeError(error) {
  const flatten = (value) => typeof value === "object" && value ? Object.values(value).map(flatten).join(" ") : String(value || "");
  return error?.status < 500 ? flatten(error.payload) : "The request could not be completed. Please retry.";
}

export function useNumberSearch(path, search, page = 1) {
  const [state, setState] = useState({ rows: [], loading: false, error: "", count: 0, key: "" });
  const key = `${path}|${search}|${page}`;
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      if (!path || !search.trim()) return;
      setState({ rows: [], loading: true, error: "", count: 0, key });
      try {
        const payload = await clientRequest(apiPath(`${path}${path.includes("?") ? "&" : "?"}search=${encodeURIComponent(search.trim())}&page=${page}&page_size=20`));
        if (!cancelled) setState({ rows: paymentList(payload), count: payload.count || 0, loading: false, error: "", key });
      } catch (error) {
        if (!cancelled) setState({ rows: [], loading: false, error: safeError(error), count: 0, key });
      }
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [path, search, page, key]);
  return state.key === key ? state : { rows: [], loading: Boolean(path && search.trim()), error: "", count: 0 };
}

export default function PaymentNumberPicker({ agency, agencyName, user, value, onSelect, disabled }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [quick, setQuick] = useState(null);
  const [payerSearch, setPayerSearch] = useState("");
  const [payerPage, setPayerPage] = useState(1);
  const [payer, setPayer] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const successRef = useRef(null);
  const canCreate = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => String(item.agency?.id ?? item.agency) === String(agency) && item.can_edit);
  const results = useNumberSearch(canCreate && agency ? `agencies/${agency}/payment-numbers/` : "", search, page);
  // Payer searches must carry the selected agency on every request.
  const scopedPayers = useNumberSearch(quick && agency ? `payment-payers/?agency=${agency}&active=true` : "", payerSearch, payerPage);
  useEffect(() => { if (success) successRef.current?.focus(); }, [success]);
  async function create() {
    if (pendingRef.current || !payer || !quick?.confirmed || !quick.sub_agent_number || !quick.terminal_number) return;
    pendingRef.current = true; setPending(true); setError("");
    try {
      const created = await clientRequest(apiPath(`agencies/${agency}/payment-numbers/`), { method: "POST", body: JSON.stringify({ ...quick, payer: payer.id }) });
      if (!mounted.current) return;
      setQuick(null); setPayer(null); setPayerSearch(""); setSearch(""); setSuccess(true); onSelect(created);
    } catch (failure) { setError(safeError(failure)); }
    finally { pendingRef.current = false; setPending(false); }
  }
  return <section className="payment-number-picker" aria-label="Select Sub-Agent Number">
    <label>Search Sub-Agent Number, Terminal Number or payer name<input disabled={disabled || pending || !canCreate} maxLength={100} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); onSelect(null); setSuccess(false); }} /></label>
    {!canCreate ? <p role="status">Agency edit permission is required to search or add payment numbers.</p> : null}
    {results.loading ? <p role="status">Searching…</p> : null}
    {results.error ? <p role="alert">{results.error}</p> : null}
    <ul className="payment-number-results" aria-label="Matching Sub-Agent Numbers">{results.rows.map((row) => <li key={`${row.id}-${row.payer}`}><button type="button" className="secondary-button" disabled={!row.selectable || disabled || pending} aria-pressed={value?.id === row.id && value?.payer === row.payer} onClick={() => { onSelect(row); setQuick(null); }}>
      {row.payer_name} · Sub-Agent Number {row.sub_agent_number} · Terminal {row.terminal_number || "Not assigned"} · {row.agency_name} · {row.is_active ? "Active" : "Inactive"} · Outstanding {formatPaymentMoney(row.outstanding_balance)} · {row.open_obligation_count} open obligations
    </button></li>)}</ul>
    {results.count > 20 ? <div className="card-actions"><button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous results</button><span>Page {page}</span><button type="button" disabled={page * 20 >= results.count} onClick={() => setPage(page + 1)}>Next results</button></div> : null}
    {canCreate && search.trim() && !results.loading && !results.error && !results.rows.length ? <div><p role="status">Sub-Agent or Terminal Number not found in this agency.</p><button type="button" className="secondary-button" disabled={disabled || pending} onClick={() => { setQuick({ sub_agent_number: "", terminal_number: "", confirmed: false }); setError(""); }}>Add Sub-Agent and Terminal Number</button></div> : null}
    {success ? <div ref={successRef} tabIndex={-1} role="status" aria-live="polite">Sub-Agent and Terminal Number added successfully.</div> : null}
    {value ? <p role="status">Selected: {value.payer_name} · Sub-Agent Number {value.sub_agent_number} · Terminal {value.terminal_number || "Not assigned"} · {value.agency_name}</p> : null}
    {quick ? <fieldset disabled={pending || disabled}><legend>Add Sub-Agent and Terminal Number</legend><p>Agency: {agencyName}</p>
      <label>Search existing payer<input value={payerSearch} onChange={(event) => { setPayerSearch(event.target.value); setPayer(null); setPayerPage(1); }} /></label>
      {scopedPayers.loading ? <p role="status">Searching payers…</p> : null}
      {scopedPayers.error ? <p role="alert">{scopedPayers.error}</p> : null}
      <ul className="payment-number-results">{scopedPayers.rows.map((row) => <li key={row.id}><button type="button" aria-pressed={payer?.id === row.id} onClick={() => setPayer(row)}>{row.payer_name}</button></li>)}</ul>
      {scopedPayers.count > 20 ? <div><button type="button" disabled={payerPage === 1} onClick={() => setPayerPage(payerPage - 1)}>Previous payers</button><button type="button" disabled={payerPage * 20 >= scopedPayers.count} onClick={() => setPayerPage(payerPage + 1)}>Next payers</button></div> : null}
      {payer ? <p>Selected payer: {payer.payer_name}</p> : null}
      <Link className="text-link" href={`/dashboard/payments/payers?create=1&agency=${agency}`} target="_blank" rel="noopener noreferrer">Add Payer (opens existing workflow in a new tab)</Link>
      <label>New Sub-Agent Number<input maxLength={80} value={quick.sub_agent_number} onChange={(event) => setQuick({ ...quick, sub_agent_number: event.target.value })} /></label>
      <label>New Terminal Number<input maxLength={80} value={quick.terminal_number} onChange={(event) => setQuick({ ...quick, terminal_number: event.target.value })} /></label>
      <label><input type="checkbox" checked={quick.confirmed} onChange={(event) => setQuick({ ...quick, confirmed: event.target.checked })} />I confirm these new numbers belong to the selected payer and agency.</label>
      {error ? <p role="alert">{error}</p> : null}
      <button type="button" className="primary-button" disabled={pending || !payer || !quick.confirmed || !quick.sub_agent_number || !quick.terminal_number} aria-busy={pending} onClick={create}>{pending ? "Adding…" : "Add numbers"}</button>
      <button type="button" onClick={() => { setQuick(null); setPayer(null); setPayerSearch(""); setError(""); }}>Cancel adding numbers</button>
    </fieldset> : null}
  </section>;
}
