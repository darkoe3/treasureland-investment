"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2, ChevronRight, Download, Link2, Plus, RotateCcw, Search, ShieldAlert, SlidersHorizontal, X } from "lucide-react";
import { apiPath, clientDownload, clientRequest } from "../lib/client-api";
import { analyticsQuery, createPaymentIdempotencyKey, formatGhanaMoney, paymentFingerprint, paymentList, paymentMoney, paymentStatusLabel } from "../lib/payment-operations";

const EMPTY_FILTERS = { agency: "", payer: "", status: "", payment_method: "", obligation_start: "", obligation_end: "", payment_start: "", payment_end: "" };
const EMPTY_PAYMENT = { amount_received: "", payment_method: "CASH", payment_reference: "", notes: "", payment_date: "" };

function errorText(error) {
  if (!error) return "";
  if (typeof error === "string") return error;
  if (Array.isArray(error)) return error.map(errorText).filter(Boolean).join(" ");
  if (typeof error === "object") return Object.values(error).map(errorText).filter(Boolean).join(" ");
  return String(error);
}

function apiError(failure) {
  return failure?.status < 500 && failure?.payload ? failure.payload : { detail: failure?.message || "The request could not be completed. Please retry." };
}

function StatusBadge({ status }) {
  return <span className={`payment-status status-${String(status || "unknown").toLowerCase()}`}><span aria-hidden="true" className="status-dot" />{paymentStatusLabel(status)}</span>;
}

function Metric({ label, value, detail, tone = "" }) {
  return <div className={`payment-metric ${tone}`}><span>{label}</span><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</div>;
}

function Loading() { return <div className="payment-loading" role="status"><span /> <span /> <span /> Loading payment records…</div>; }

function ErrorBox({ error }) { return error ? <div className="payment-alert" role="alert"><ShieldAlert size={18} aria-hidden="true" /><span>{errorText(error)}</span></div> : null; }

function FilterBar({ filters, setFilters, agencies, payers, showPayment = true }) {
  function change(key, value) { setFilters((current) => ({ ...current, [key]: value })); }
  return <div className="payment-filter-bar panel">
    <div className="filter-heading"><SlidersHorizontal size={18} aria-hidden="true" /><strong>Filter records</strong></div>
    <label>Agency<select value={filters.agency || ""} onChange={(event) => change("agency", event.target.value)}><option value="">All agencies</option>{agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label>
    {payers ? <label>Payer<select value={filters.payer || ""} onChange={(event) => change("payer", event.target.value)}><option value="">All payers</option>{payers.map((payer) => <option key={payer.id} value={payer.id}>{payer.payer_name}</option>)}</select></label> : null}
    {showPayment ? <label>Status<select value={filters.status || ""} onChange={(event) => change("status", event.target.value)}><option value="">All statuses</option><option value="OPEN">Open</option><option value="PARTIALLY_PAID">Partially paid</option><option value="PAID">Paid</option><option value="CANCELLED">Cancelled</option><option value="POSTED">Posted</option><option value="REVERSED">Reversed</option></select></label> : null}
    {showPayment ? <label>Method<select value={filters.payment_method || ""} onChange={(event) => change("payment_method", event.target.value)}><option value="">All methods</option><option value="CASH">Cash</option><option value="MOBILE_MONEY">Mobile Money</option><option value="BANK_TRANSFER">Bank transfer</option><option value="CHEQUE">Cheque</option><option value="OTHER">Other</option></select></label> : null}
    <label>Obligation from<input type="date" value={filters.obligation_start || ""} onChange={(event) => change("obligation_start", event.target.value)} /></label>
    <label>Obligation to<input type="date" value={filters.obligation_end || ""} onChange={(event) => change("obligation_end", event.target.value)} /></label>
    <label>Payment from<input type="date" value={filters.payment_start || ""} onChange={(event) => change("payment_start", event.target.value)} /></label>
    <label>Payment to<input type="date" value={filters.payment_end || ""} onChange={(event) => change("payment_end", event.target.value)} /></label>
  </div>;
}

function PageHeading({ eyebrow, title, copy, action }) {
  return <header className="payment-page-heading"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2>{copy ? <p>{copy}</p> : null}</div>{action}</header>;
}

function Empty({ children }) { return <div className="payment-empty"><CheckCircle2 size={24} aria-hidden="true" /><p>{children}</p></div>; }

function usePaymentData(view, recordId, user) {
  const [state, setState] = useState({ loading: true, error: "", data: {} });
  const reload = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const agenciesPayload = await clientRequest(apiPath("agencies/?page_size=100"));
      const agencies = paymentList(agenciesPayload);
      if (view === "overview" || view === "analytics") {
        const query = view === "analytics" ? "" : "&page_size=8";
        const [analytics, payments, obligations] = await Promise.all([
          clientRequest(apiPath(`payments/analytics/${query ? `?${query.slice(1)}` : ""}`)),
          view === "overview" ? clientRequest(apiPath("payer-payments/?page_size=8")) : Promise.resolve([]),
          view === "overview" ? clientRequest(apiPath("payment-obligations/?outstanding_only=true&page_size=8")) : Promise.resolve([]),
        ]);
        setState({ loading: false, error: "", data: { agencies, analytics, payments: paymentList(payments), obligations: paymentList(obligations) } });
      } else if (view === "payers") {
        const payload = await clientRequest(apiPath("payment-payers/?page_size=100"));
        setState({ loading: false, error: "", data: { agencies, payers: paymentList(payload) } });
      } else if (view === "payer") {
        const [payer, obligations, codes, payers] = await Promise.all([
          clientRequest(apiPath(`payment-payers/${recordId}/`)),
          clientRequest(apiPath(`payment-obligations/?payer=${recordId}&page_size=100`)),
          clientRequest(apiPath(`tpm-codes/?page_size=100`)),
          clientRequest(apiPath("payment-payers/?page_size=100")),
        ]);
        setState({ loading: false, error: "", data: { agencies, payer, payers: paymentList(payers), obligations: paymentList(obligations), codes: paymentList(codes) } });
      } else if (view === "obligations") {
        const [obligations, payers] = await Promise.all([
          clientRequest(apiPath("payment-obligations/?page_size=100")),
          clientRequest(apiPath("payment-payers/?page_size=100")),
        ]);
        setState({ loading: false, error: "", data: { agencies, obligations: paymentList(obligations), payers: paymentList(payers) } });
      } else if (view === "obligation") {
        const [obligation, payments] = await Promise.all([
          clientRequest(apiPath(`payment-obligations/${recordId}/`)),
          clientRequest(apiPath(`payer-payments/?obligation=${recordId}&page_size=100`)),
        ]);
        setState({ loading: false, error: "", data: { agencies, obligation, payments: paymentList(payments) } });
      } else if (view === "receipt") {
        const payment = await clientRequest(apiPath(`payer-payments/${recordId}/`));
        setState({ loading: false, error: "", data: { agencies, payment } });
      }
    } catch (failure) {
      setState({ loading: false, error: apiError(failure), data: {} });
    }
  }, [view, recordId]);
  useEffect(() => {
    const timer = setTimeout(() => { reload(); }, 0);
    return () => clearTimeout(timer);
  }, [reload]);
  return { ...state, reload };
}

function QuickActions({ user }) {
  const canManage = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.can_create);
  return (
    <section className="payment-quick-actions panel" aria-label="Payment quick actions">
      <div className="quick-action-row">
        {canManage ? <Link className="primary-button" href="/dashboard/payments/payers?create=1"><Plus size={17} aria-hidden="true" />Add payer</Link> : null}
        <Link className="secondary-button" href="/dashboard/payments/payers">Manage payers</Link>
        {canManage ? <Link className="primary-button" href="/dashboard/payments/obligations?create=1"><Plus size={17} aria-hidden="true" />New obligation</Link> : null}
        <Link className="secondary-button" href="/dashboard/payments/obligations">View obligations</Link>
        <Link className="secondary-button" href="/dashboard/payments/analytics">Payment analytics</Link>
      </div>
      <p className="payment-hint">Create or select a payer before creating a payment obligation.</p>
    </section>
  );
}

function Overview({ data, user, onRefresh }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const analytics = data.analytics || {};
  const portfolio = analytics.obligation_portfolio || {};
  const collections = analytics.collections || {};
  const filteredNotice = Object.values(filters).some(Boolean) ? "Filters apply on the analytics screen." : "All permitted agencies";
  return <div className="page-stack payment-workspace">
    <PageHeading eyebrow="Payment operations" title="Collections overview" copy="A focused view of obligations, receipts, and outstanding balances." action={<Link className="primary-button" href="/dashboard/payments/obligations"><Plus size={17} aria-hidden="true" />Record a payment</Link>} />
    <QuickActions user={user} />
    <div className="payment-filter-summary"><span>{filteredNotice}</span><Link className="text-link" href="/dashboard/payments/analytics">Open full analytics <ChevronRight size={15} aria-hidden="true" /></Link></div>
    <section className="payment-metric-grid" aria-label="Payment totals">
      <Metric label="Total expected" value={formatGhanaMoney(portfolio.total_expected)} />
      <Metric label="Net collected" value={formatGhanaMoney(collections.net_collected_amount)} tone="positive" detail={`Gross ${formatGhanaMoney(collections.gross_posted_amount)}`} />
      <Metric label="Outstanding" value={formatGhanaMoney(portfolio.total_outstanding)} tone="warning" />
      <Metric label="Collection rate" value={`${portfolio.collection_rate || "0.00"}%`} />
    </section>
    <section className="payment-stat-strip"><div><strong>{portfolio.status_counts?.OPEN || 0}</strong><span>Open obligations</span></div><div><strong>{portfolio.status_counts?.PARTIALLY_PAID || 0}</strong><span>Partially paid</span></div><div><strong>{portfolio.status_counts?.PAID || 0}</strong><span>Paid obligations</span></div><div><strong>{formatGhanaMoney(collections.reversed_amount)}</strong><span>Reversed</span></div></section>
    <div className="payment-content-grid"><section className="panel payment-table-panel"><div className="panel-heading"><div><p className="eyebrow">Recent activity</p><h3>Recent payments</h3></div><Link className="text-link" href="/dashboard/payments/obligations">View obligations</Link></div><PaymentTable rows={data.payments || []} /></section><section className="panel payment-table-panel"><div className="panel-heading"><div><p className="eyebrow">Needs attention</p><h3>Outstanding obligations</h3></div><button className="icon-button" type="button" onClick={onRefresh} aria-label="Refresh payment overview" title="Refresh"><RotateCcw size={17} aria-hidden="true" /></button></div><ObligationTable rows={data.obligations || []} /></section></div>
    <p className="payment-note">Payment records are independent of Daily Sheets. Reversed receipts remain available for download and are excluded from active collections.</p>
  </div>;
}

function PaymentTable({ rows }) {
  return rows.length ? <div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Receipt</th><th>Date</th><th>Amount</th><th>Method</th><th>Status</th></tr></thead><tbody>{rows.map((payment) => <tr key={payment.id}><td><Link className="text-link" href={`/dashboard/payments/receipts/${payment.id}`}>{payment.receipt_number}</Link></td><td>{String(payment.payment_date || "").slice(0, 10)}</td><td>{formatGhanaMoney(payment.amount_received)}</td><td>{paymentStatusLabel(payment.payment_method)}</td><td><StatusBadge status={payment.status} /></td></tr>)}</tbody></table></div> : <Empty>No payment receipts match the current view.</Empty>;
}

function ObligationTable({ rows }) {
  return rows.length ? <div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Obligation</th><th>Payer</th><th>Balance</th><th>Status</th></tr></thead><tbody>{rows.map((obligation) => <tr key={obligation.id}><td><Link className="text-link" href={`/dashboard/payments/obligations/${obligation.id}`}>{obligation.obligation_number}</Link><small>{obligation.description}</small></td><td>{obligation.payer_name}</td><td>{formatGhanaMoney(obligation.balance)}</td><td><StatusBadge status={obligation.status} /></td></tr>)}</tbody></table></div> : <Empty>No outstanding obligations.</Empty>;
}

function Payers({ data, user, onRefresh }) {
  const [search, setSearch] = useState("");
  const canCreate = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.can_create);
  // Lazy initializer opens the create panel on first render only when ?create=1 is present and permitted.
  const [form, setForm] = useState(() => (canCreate && typeof window !== "undefined" && new URLSearchParams(window.location.search).get("create") === "1")
    ? { agency: data.agencies[0]?.id || "", payer_name: "", telephone: "", email: "", address: "", notes: "" }
    : null);
  const [error, setError] = useState("");
  const canEdit = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.can_edit);
  const visible = (data.payers || []).filter((payer) => !search || `${payer.payer_name} ${payer.agency_name}`.toLowerCase().includes(search.toLowerCase()));

  async function save(event) {
    event.preventDefault();
    setError("");
    try {
      await clientRequest(apiPath(form.id ? `payment-payers/${form.id}/` : "payment-payers/"), { method: form.id ? "PATCH" : "POST", body: JSON.stringify(form) });
      setForm(null);
      onRefresh();
    } catch (failure) {
      setError(apiError(failure));
    }
  }

  async function toggle(payer) {
    if (!window.confirm(`${payer.is_active ? "Deactivate" : "Activate"} ${payer.payer_name}?`)) return;
    try {
      await clientRequest(apiPath(`payment-payers/${payer.id}/${payer.is_active ? "deactivate" : "reactivate"}/`), { method: "POST", body: JSON.stringify({}) });
      onRefresh();
    } catch (failure) {
      setError(apiError(failure));
    }
  }

  return (
    <div className="page-stack payment-workspace">
      <PageHeading eyebrow="Payment directory" title="Payers" copy="Manage payment names within their agencies. Historical receipts remain unchanged after reassignment." action={canCreate ? <button className="primary-button" type="button" onClick={() => setForm({ agency: data.agencies[0]?.id || "", payer_name: "", telephone: "", email: "", address: "", notes: "" })}><Plus size={17} aria-hidden="true" />Add payer</button> : null} />
      <div className="payment-search"><Search size={18} aria-hidden="true" /><input aria-label="Search payers" placeholder="Search payer or agency" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
      <ErrorBox error={error} />
      <section className="payer-grid">{visible.map((payer) => <article className="panel payer-card" key={payer.id}><div className="payer-card-top"><div><p className="eyebrow">{payer.agency_name}</p><h3>{payer.payer_name}</h3></div><StatusBadge status={payer.is_active ? "ACTIVE" : "INACTIVE"} /></div><dl className="compact-stats"><div><dt>Expected</dt><dd>{formatGhanaMoney(payer.total_expected)}</dd></div><div><dt>Outstanding</dt><dd>{formatGhanaMoney(payer.total_outstanding)}</dd></div><div><dt>Obligations</dt><dd>{payer.active_obligations || 0}</dd></div></dl><div className="card-actions"><Link className="secondary-button" href={`/dashboard/payments/payers/${payer.id}`}>View payer</Link>{canEdit && <button className="icon-text-button" type="button" onClick={() => setForm({ id: payer.id, agency: payer.agency, payer_name: payer.payer_name, telephone: payer.telephone || "", email: payer.email || "", address: payer.address || "", notes: payer.notes || "" })}>Edit</button>}{canEdit && <button className="icon-text-button" type="button" onClick={() => toggle(payer)}>{payer.is_active ? "Deactivate" : "Activate"}</button>}</div></article>)}{!visible.length ? <Empty>No payers match this search.</Empty> : null}</section>
      {form ? <dialog open className="payment-dialog"><form onSubmit={save}><div className="dialog-heading"><h3>{form.id ? "Edit payer" : "Add payer"}</h3><button className="icon-button" type="button" onClick={() => setForm(null)} aria-label="Close payer form"><X size={18} /></button></div><label>Agency<select required disabled={Boolean(form.id)} value={form.agency} onChange={(event) => setForm({ ...form, agency: event.target.value })}>{data.agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label><label>Payer name<input required maxLength={200} value={form.payer_name} onChange={(event) => setForm({ ...form, payer_name: event.target.value })} /></label><label>Telephone<input value={form.telephone} onChange={(event) => setForm({ ...form, telephone: event.target.value })} /></label><label>Email<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label><label>Address<input value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></label><ErrorBox error={error} /><button className="primary-button" type="submit">Save payer</button></form></dialog> : null}
    </div>
  );
}

function Obligations({ data, user, onRefresh }) {
  const [filters, setFilters] = useState({ agency: "", payer: "", status: "" });
  const canCreate = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.can_create);
  // Lazy initializer opens the create panel on first render only when ?create=1 is present and permitted.
  const [form, setForm] = useState(() => (canCreate && typeof window !== "undefined" && new URLSearchParams(window.location.search).get("create") === "1")
    ? { agency: data.agencies[0]?.id || "", payer: data.payers[0]?.id || "", description: "", obligation_date: "", total_expected: "", notes: "" }
    : null);
  const [error, setError] = useState("");
  const visible = (data.obligations || []).filter((item) => (!filters.agency || String(item.agency) === filters.agency) && (!filters.payer || String(item.payer) === filters.payer) && (!filters.status || item.status === filters.status));
  async function create(event) { event.preventDefault(); setError(""); try { await clientRequest(apiPath("payment-obligations/"), { method: "POST", body: JSON.stringify({ ...form, total_expected: form.total_expected }) }); setForm(null); onRefresh(); } catch (failure) { setError(apiError(failure)); } }
  return <div className="page-stack payment-workspace"><PageHeading eyebrow="Payment ledger" title="Obligations" copy="Create expected amounts, monitor balances, and open an obligation to record receipts." action={canCreate ? <button className="primary-button" type="button" onClick={() => setForm({ agency: data.agencies[0]?.id || "", payer: data.payers[0]?.id || "", description: "", obligation_date: "", total_expected: "", notes: "" })}><Plus size={17} aria-hidden="true" />Create obligation</button> : null} /><div className="payment-filter-bar panel"><label>Agency<select value={filters.agency} onChange={(event) => setFilters({ ...filters, agency: event.target.value })}><option value="">All agencies</option>{data.agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label><label>Payer<select value={filters.payer} onChange={(event) => setFilters({ ...filters, payer: event.target.value })}><option value="">All payers</option>{data.payers.filter((payer) => !filters.agency || String(payer.agency) === filters.agency).map((payer) => <option key={payer.id} value={payer.id}>{payer.payer_name}</option>)}</select></label><label>Status<select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option>{["OPEN", "PARTIALLY_PAID", "PAID", "CANCELLED"].map((status) => <option key={status} value={status}>{paymentStatusLabel(status)}</option>)}</select></label></div><ErrorBox error={error} /><section className="panel payment-table-panel"><div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Obligation</th><th>Agency / payer</th><th>Date</th><th>Expected</th><th>Posted</th><th>Reversed</th><th>Balance</th><th>Status</th></tr></thead><tbody>{visible.map((item) => <tr key={item.id}><td><Link className="text-link" href={`/dashboard/payments/obligations/${item.id}`}>{item.obligation_number}</Link><small>{item.description}</small></td><td>{item.agency_name}<small>{item.payer_name}</small></td><td>{item.obligation_date}</td><td>{formatGhanaMoney(item.total_expected)}</td><td>{formatGhanaMoney(item.total_paid)}</td><td>{formatGhanaMoney(item.reversed_total)}</td><td>{formatGhanaMoney(item.balance)}</td><td><StatusBadge status={item.status} /></td></tr>)}</tbody></table></div>{!visible.length ? <Empty>No obligations match these filters.</Empty> : null}</section>{form ? <dialog open className="payment-dialog"><form onSubmit={create}><div className="dialog-heading"><h3>Create obligation</h3><button className="icon-button" type="button" onClick={() => setForm(null)} aria-label="Close obligation form"><X size={18} /></button></div><label>Agency<select required value={form.agency} onChange={(event) => setForm({ ...form, agency: event.target.value, payer: "" })}>{data.agencies.map((agency) => <option key={agency.id} value={agency.id}>{agency.name}</option>)}</select></label><label>Payer<select required value={form.payer} onChange={(event) => setForm({ ...form, payer: event.target.value })}>{data.payers.filter((payer) => String(payer.agency) === String(form.agency)).map((payer) => <option key={payer.id} value={payer.id}>{payer.payer_name}</option>)}</select></label><label>Description<input required value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label><label>Obligation date<input required type="date" value={form.obligation_date} onChange={(event) => setForm({ ...form, obligation_date: event.target.value })} /></label><label>Total expected<input required min="0.01" step="0.01" type="number" value={form.total_expected} onChange={(event) => setForm({ ...form, total_expected: event.target.value })} /></label><ErrorBox error={error} /><button className="primary-button" type="submit">Create obligation</button></form></dialog> : null}</div>;
}

function ObligationDetail({ data, user, onRefresh }) {
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [error, setError] = useState("");
  const obligation = data.obligation;
  const canRecord = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.agency.id === obligation?.agency && item.can_create);
  const canCancel = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.agency.id === obligation?.agency && item.can_delete);
  async function cancel(event) { event.preventDefault(); setError(""); try { await clientRequest(apiPath(`payment-obligations/${obligation.id}/cancel/`), { method: "POST", body: JSON.stringify({ reason: event.currentTarget.reason.value }) }); setCancelOpen(false); onRefresh(); } catch (failure) { setError(apiError(failure)); } }
  if (!obligation) return null;
  return <div className="page-stack payment-workspace"><Link className="back-link" href="/dashboard/payments/obligations"><ArrowLeft size={16} aria-hidden="true" />All obligations</Link><PageHeading eyebrow={`${obligation.agency_name} · ${obligation.payer_name}`} title={obligation.obligation_number} copy={obligation.description} action={<div className="card-actions">{canRecord && obligation.status !== "CANCELLED" && obligation.status !== "PAID" ? <button className="primary-button" type="button" onClick={() => setPaymentOpen(true)}>Record payment</button> : null}{canCancel && obligation.status !== "CANCELLED" && obligation.status !== "PAID" ? <button className="danger-button" type="button" onClick={() => setCancelOpen(true)}>Cancel obligation</button> : null}</div>} /><div className="payment-metric-grid"><Metric label="Expected" value={formatGhanaMoney(obligation.total_expected)} /><Metric label="Posted" value={formatGhanaMoney(obligation.total_paid)} tone="positive" /><Metric label="Reversed" value={formatGhanaMoney(obligation.reversed_total)} /><Metric label="Balance" value={formatGhanaMoney(obligation.balance)} tone="warning" /></div><div className="detail-meta"><span>Obligation date <strong>{obligation.obligation_date}</strong></span><span>Status <StatusBadge status={obligation.status} /></span></div>{obligation.status === "PAID" ? <p className="payment-note">This obligation is fully paid. Posted payments cannot be edited or deleted.</p> : null}{obligation.status === "CANCELLED" ? <p className="payment-note">This obligation is cancelled and cannot receive payments.</p> : null}<ErrorBox error={error} /><section className="panel payment-table-panel"><div className="panel-heading"><div><p className="eyebrow">Immutable ledger</p><h3>Payment history</h3></div></div><PaymentTable rows={data.payments || []} /></section>{paymentOpen ? <PaymentForm obligation={obligation} user={user} onClose={() => setPaymentOpen(false)} onSuccess={() => { setPaymentOpen(false); onRefresh(); }} /> : null}{cancelOpen ? <dialog open className="payment-dialog"><form onSubmit={cancel}><div className="dialog-heading"><h3>Cancel obligation</h3><button className="icon-button" type="button" onClick={() => setCancelOpen(false)} aria-label="Close cancellation"><X size={18} /></button></div><p>This cannot be undone and obligations with posted payments cannot be cancelled.</p><label>Required reason<textarea name="reason" required maxLength={500} rows="4" /></label><button className="danger-button" type="submit">Confirm cancellation</button></form></dialog> : null}</div>;
}

function PaymentForm({ obligation, onClose, onSuccess }) {
  const [form, setForm] = useState(EMPTY_PAYMENT);
  const [error, setError] = useState("");
  const [fields, setFields] = useState({});
  const [pending, setPending] = useState(false);
  const keyRef = useRef(createPaymentIdempotencyKey());
  const fingerprintRef = useRef(paymentFingerprint(form));
  function update(next) { const value = { ...form, ...next }; if (paymentFingerprint(value) !== fingerprintRef.current) { keyRef.current = createPaymentIdempotencyKey(); fingerprintRef.current = paymentFingerprint(value); } setForm(value); }
  async function submit(event) {
    event.preventDefault(); if (pending) return;
    setPending(true); setError(""); setFields({});
    try { await clientRequest(apiPath("payer-payments/"), { method: "POST", body: JSON.stringify({ ...form, obligation: obligation.id, idempotency_key: keyRef.current }) }); onSuccess(); }
    catch (failure) { setError(apiError(failure)); setFields(failure?.payload || {}); }
    finally { setPending(false); }
  }
  return <dialog open className="payment-dialog payment-form-dialog"><form onSubmit={submit}><div className="dialog-heading"><div><p className="eyebrow">New receipt</p><h3>Record payment</h3></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close payment form"><X size={18} /></button></div><div className="payment-confirmation"><strong>{obligation.payer_name}</strong><span>{obligation.agency_name} · {obligation.obligation_number}</span><span>Expected {formatGhanaMoney(obligation.total_expected)} · Already paid {formatGhanaMoney(obligation.total_paid)} · Balance {formatGhanaMoney(obligation.balance)}</span></div><label>Amount received<input required min="0.01" max={paymentMoney(obligation.balance)} step="0.01" type="number" value={form.amount_received} onChange={(event) => update({ amount_received: event.target.value })} aria-describedby="amount-error" />{fields.amount_received ? <span id="amount-error" className="field-error" role="alert">{errorText(fields.amount_received)}</span> : null}</label><label>Payment method<select value={form.payment_method} onChange={(event) => update({ payment_method: event.target.value })}><option value="CASH">Cash</option><option value="MOBILE_MONEY">Mobile Money</option><option value="BANK_TRANSFER">Bank transfer</option><option value="CHEQUE">Cheque</option><option value="OTHER">Other</option></select></label>{form.payment_method !== "CASH" ? <label>Reference<input required value={form.payment_reference} onChange={(event) => update({ payment_reference: event.target.value })} />{fields.payment_reference ? <span className="field-error" role="alert">{errorText(fields.payment_reference)}</span> : null}</label> : null}<label>Payment date<input type="date" value={form.payment_date} onChange={(event) => update({ payment_date: event.target.value })} /></label><label>Note <span className="muted">optional</span><textarea rows="2" value={form.notes} onChange={(event) => update({ notes: event.target.value })} /></label><ErrorBox error={error} /><div className="dialog-actions"><button className="secondary-button" type="button" onClick={onClose} disabled={pending}>Cancel</button><button className="primary-button" type="submit" disabled={pending}>{pending ? "Posting…" : "Post payment"}</button></div></form></dialog>;
}

function Receipt({ data, onDownload }) {
  const payment = data.payment;
  return <div className="page-stack payment-workspace"><Link className="back-link" href={payment?.obligation ? `/dashboard/payments/obligations/${payment.obligation}` : "/dashboard/payments"}><ArrowLeft size={16} aria-hidden="true" />Back to payment</Link><PageHeading eyebrow="Receipt" title={payment?.receipt_number || "Payment receipt"} copy="This receipt is generated by the backend ledger." action={payment ? <button className="primary-button" type="button" onClick={() => onDownload(payment)}> <Download size={17} aria-hidden="true" />Download receipt</button> : null} />{payment ? <section className="panel receipt-summary"><div className="receipt-ribbon"><span>Status</span><StatusBadge status={payment.status} /></div><dl><div><dt>Payer</dt><dd>{payment.payer_name}</dd></div><div><dt>Agency</dt><dd>{payment.agency_name}</dd></div><div><dt>Obligation</dt><dd>{payment.obligation_number}</dd></div><div><dt>Amount</dt><dd>{formatGhanaMoney(payment.amount_received)}</dd></div><div><dt>Method</dt><dd>{paymentStatusLabel(payment.payment_method)}</dd></div><div><dt>Recorded by</dt><dd>{payment.recorded_by_display_snapshot || "Authorised recorder"}</dd></div></dl>{payment.status === "REVERSED" ? <p className="payment-note">This receipt is reversed. The original PDF remains available.</p> : null}</section> : <Empty>Receipt not found.</Empty>}</div>;
}

function Analytics({ data }) {
  const [filters, setFilters] = useState({ agencies: [], payer: "", obligation_status: "", obligation_start: "", obligation_end: "", payment_start: "", payment_end: "", payment_method: "" });
  const [result, setResult] = useState(data.analytics);
  const [error, setError] = useState("");
  const agencies = data.agencies || [];
  async function apply(event) { event.preventDefault(); setError(""); try { setResult(await clientRequest(apiPath(`payments/analytics/?${analyticsQuery(filters)}`))); } catch (failure) { setError(apiError(failure)); } }
  const portfolio = result?.obligation_portfolio || {};
  const collections = result?.collections || {};
  return <div className="page-stack payment-workspace"><PageHeading eyebrow="Payment intelligence" title="Analytics" copy="Obligation dates filter the portfolio. Payment dates filter collections. Both ranges are inclusive." /><form className="panel analytics-filters" onSubmit={apply}><div className="analytics-agencies"><span>Agencies</span>{agencies.map((agency) => <label key={agency.id}><input type="checkbox" checked={filters.agencies.includes(String(agency.id))} onChange={(event) => setFilters({ ...filters, agencies: event.target.checked ? [...filters.agencies, String(agency.id)] : filters.agencies.filter((id) => id !== String(agency.id)) })} />{agency.name}</label>)}</div><div className="date-filter-grid"><label>Obligation from<input type="date" value={filters.obligation_start} onChange={(event) => setFilters({ ...filters, obligation_start: event.target.value })} /></label><label>Obligation to<input type="date" value={filters.obligation_end} onChange={(event) => setFilters({ ...filters, obligation_end: event.target.value })} /></label><label>Payment from<input type="date" value={filters.payment_start} onChange={(event) => setFilters({ ...filters, payment_start: event.target.value })} /></label><label>Payment to<input type="date" value={filters.payment_end} onChange={(event) => setFilters({ ...filters, payment_end: event.target.value })} /></label></div><label>Payment method<select value={filters.payment_method} onChange={(event) => setFilters({ ...filters, payment_method: event.target.value })}><option value="">All methods</option><option value="CASH">Cash</option><option value="MOBILE_MONEY">Mobile Money</option><option value="BANK_TRANSFER">Bank transfer</option><option value="CHEQUE">Cheque</option><option value="OTHER">Other</option></select></label><button className="primary-button" type="submit">Apply filters</button><ErrorBox error={error} /></form><section className="payment-metric-grid"><Metric label="Expected" value={formatGhanaMoney(portfolio.total_expected)} /><Metric label="Gross posted" value={formatGhanaMoney(collections.gross_posted_amount)} /><Metric label="Reversed" value={formatGhanaMoney(collections.reversed_amount)} tone="warning" /><Metric label="Net collected" value={formatGhanaMoney(collections.net_collected_amount)} tone="positive" /><Metric label="Outstanding" value={formatGhanaMoney(portfolio.total_outstanding)} /></section><div className="analytics-grid"><section className="panel analytics-section"><div className="panel-heading"><h3>Status breakdown</h3><span>{portfolio.obligation_count || 0} obligations</span></div><dl className="analytics-list">{Object.entries(portfolio.status_counts || {}).map(([status, count]) => <div key={status}><dt><StatusBadge status={status} /></dt><dd>{count}</dd></div>)}</dl></section><section className="panel analytics-section"><div className="panel-heading"><h3>Payment methods</h3><span>Net collected</span></div><div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Method</th><th>Gross</th><th>Reversed</th><th>Net</th></tr></thead><tbody>{Object.entries(collections.by_payment_method || {}).map(([method, row]) => <tr key={method}><td>{row.label || paymentStatusLabel(method)}</td><td>{formatGhanaMoney(row.gross_posted_amount)}</td><td>{formatGhanaMoney(row.reversed_amount)}</td><td>{formatGhanaMoney(row.net_collected_amount)}</td></tr>)}</tbody></table></div></section></div><section className="panel analytics-section"><div className="panel-heading"><h3>Collection trend</h3><span>{result?.trends?.grouping || "daily"} grouping</span></div><div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Period</th><th>Gross posted</th><th>Reversed</th><th>Net collected</th></tr></thead><tbody>{(result?.trends?.periods || []).map((row) => <tr key={row.period}><td>{row.period}</td><td>{formatGhanaMoney(row.gross_posted_amount)}</td><td>{formatGhanaMoney(row.reversed_amount)}</td><td>{formatGhanaMoney(row.net_collected_amount)}</td></tr>)}</tbody></table></div></section>{result?.agency_breakdown ? <section className="panel analytics-section"><div className="panel-heading"><h3>Agency breakdown</h3><span>Super Admin view</span></div><div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Agency</th><th>Expected</th><th>Net collected</th><th>Outstanding</th><th>Rate</th></tr></thead><tbody>{result.agency_breakdown.map((row) => <tr key={row.agency_id}><td>{row.agency_name}</td><td>{formatGhanaMoney(row.expected)}</td><td>{formatGhanaMoney(row.net_collected)}</td><td>{formatGhanaMoney(row.outstanding)}</td><td>{row.collection_rate}%</td></tr>)}</tbody></table></div></section> : null}</div>;
}

export default function PaymentsClient({ user, view = "overview", recordId = null }) {
  const state = usePaymentData(view, recordId, user);
  async function download(payment) {
    try { const result = await clientDownload(apiPath(`payer-payments/${payment.id}/receipt/`)); const url = URL.createObjectURL(result.blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${payment.receipt_number || "receipt"}.pdf`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0); } catch { /* The page stays usable when a download is denied. */ }
  }
  if (state.loading) return <div className="page-stack payment-workspace"><Loading /></div>;
  return <>
    <ErrorBox error={state.error} />
    {state.error ? <div className="payment-retry"><button className="secondary-button" type="button" onClick={state.reload}>Retry</button></div> : null}
    {!state.error && view === "overview" ? <Overview data={state.data} user={user} onRefresh={state.reload} /> : null}
    {!state.error && view === "analytics" ? <Analytics data={state.data} /> : null}
    {!state.error && view === "payers" ? <Payers data={state.data} user={user} onRefresh={state.reload} /> : null}
    {!state.error && view === "payer" ? <PayerDetail data={state.data} user={user} onRefresh={state.reload} /> : null}
    {!state.error && view === "obligations" ? <Obligations data={state.data} user={user} onRefresh={state.reload} /> : null}
    {!state.error && view === "obligation" ? <ObligationDetail data={state.data} user={user} onRefresh={state.reload} /> : null}
    {!state.error && view === "receipt" ? <Receipt data={state.data} onDownload={download} /> : null}
  </>;
}

function PayerDetail({ data, user, onRefresh }) {
  const payer = data.payer;
  const [subAgent, setSubAgent] = useState("");
  const [newPayer, setNewPayer] = useState("");
  const [error, setError] = useState("");
  const canEdit = user.role === "SUPER_ADMIN" || user.agency_assignments?.some((item) => item.agency.id === payer?.agency && item.can_edit);

  async function assign() {
    setError("");
    try {
      await clientRequest(apiPath(`payment-payers/${payer.id}/assign_sub_agent/`), { method: "POST", body: JSON.stringify({ sub_agent_number: subAgent }) });
      setSubAgent("");
      onRefresh();
    } catch (failure) {
      setError(apiError(failure));
    }
  }

  async function reassign() {
    if (!window.confirm("Reassign this Sub-Agent Number? Historical receipts will not change.")) return;
    setError("");
    try {
      await clientRequest(apiPath(`payment-payers/${payer.id}/reassign_sub_agent/`), { method: "POST", body: JSON.stringify({ sub_agent_number: subAgent, new_payer: newPayer, confirmed: true }) });
      setSubAgent("");
      setNewPayer("");
      onRefresh();
    } catch (failure) {
      setError(apiError(failure));
    }
  }

  async function unlink() {
    if (!window.confirm("Unlink this Sub-Agent Number from the payer? Historical receipts will not change.")) return;
    setError("");
    try {
      await clientRequest(apiPath(`payment-payers/${payer.id}/unassign_sub_agent/`), { method: "POST", body: JSON.stringify({ sub_agent_number: subAgent }) });
      setSubAgent("");
      onRefresh();
    } catch (failure) {
      setError(apiError(failure));
    }
  }

  if (!payer) return null;
  const targetPayers = (data.payers || []).filter((item) => item.id !== payer.id && item.agency === payer.agency);
  return (
    <div className="page-stack payment-workspace">
      <Link className="back-link" href="/dashboard/payments/payers"><ArrowLeft size={16} aria-hidden="true" />All payers</Link>
      <PageHeading eyebrow={payer.agency_name} title={payer.payer_name} copy="Payer identity is independent from historical payment snapshots." action={<StatusBadge status={payer.is_active ? "ACTIVE" : "INACTIVE"} />} />
      <div className="payment-metric-grid">
        <Metric label="Expected" value={formatGhanaMoney(payer.total_expected)} />
        <Metric label="Collected" value={formatGhanaMoney(payer.total_collected)} tone="positive" />
        <Metric label="Outstanding" value={formatGhanaMoney(payer.total_outstanding)} tone="warning" />
      </div>
      <ErrorBox error={error} />
      <section className="panel payer-assignment-panel">
        <div className="panel-heading"><div><p className="eyebrow">Agency ownership</p><h3>Sub-Agent Number actions</h3></div><Link className="text-link" href={`/dashboard/payments/payers/${payer.id}`}>Refresh</Link></div>
        <p className="payment-note">Only active Sub-Agent Numbers from {payer.agency_name} can be linked. Reassignment does not rewrite historical receipts.</p>
        {canEdit ? <div className="assignment-controls">
          <label>Sub-Agent Number<select required value={subAgent} onChange={(event) => setSubAgent(event.target.value)}><option value="">Select an active Sub-Agent Number</option>{(data.codes || []).filter((code) => code.is_active !== false && String(code.agency) === String(payer.agency)).map((code) => <option key={code.id} value={code.id}>{code.code} · {code.person_name}</option>)}</select></label>
          <button className="secondary-button" type="button" disabled={!subAgent} onClick={assign}><Link2 size={16} aria-hidden="true" />Link</button>
          <button className="danger-button" type="button" disabled={!subAgent} onClick={unlink}>Unlink</button>
          <label>New payer<select value={newPayer} onChange={(event) => setNewPayer(event.target.value)}><option value="">Select target payer</option>{targetPayers.map((item) => <option key={item.id} value={item.id}>{item.payer_name}</option>)}</select></label>
          <button className="danger-button" type="button" disabled={!subAgent || !newPayer} onClick={reassign}>Reassign</button>
        </div> : <p>Read-only access for this agency.</p>}
      </section>
      <section className="panel payment-table-panel"><div className="panel-heading"><h3>Obligations for this payer</h3><Link className="secondary-button" href="/dashboard/payments/obligations">All obligations</Link></div><ObligationTable rows={data.obligations || []} /></section>
    </div>
  );
}
