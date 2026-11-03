"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import { formatPaymentMoney, paymentList } from "../lib/payment-operations";

export function usePaymentPage(path, params, initial = []) {
  const [page, setPage] = useState(1);
  const [state, setState] = useState({ rows: initial, count: initial.length, error: "", loading: false, key: "" });
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== "" && value != null)).toString();
  const key = `${path}?${query}&page=${page}`;
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      setState((current) => ({ ...current, loading: true, error: "" }));
      try {
        const result = await clientRequest(apiPath(`${key}&page_size=20`));
        if (!cancelled) setState({ rows: paymentList(result), count: result.count || 0, error: "", loading: false, key });
      } catch { if (!cancelled) setState((current) => ({ ...current, loading: false, error: "Could not load records. Please retry.", key })); }
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [key]);
  return { ...state, loading: state.loading || state.key !== key, page, setPage };
}

export function PageControls({ state }) {
  return <div className="card-actions"><button type="button" disabled={state.page <= 1 || state.loading} onClick={() => state.setPage(state.page - 1)}>Previous page</button><span>Page {state.page} · {state.count} records</span><button type="button" disabled={state.page * 20 >= state.count || state.loading} onClick={() => state.setPage(state.page + 1)}>Next page</button>{state.loading ? <span role="status">Loading…</span> : null}{state.error ? <span role="alert">{state.error}</span> : null}</div>;
}

export function NumberTotalsTable({ rows, onHistory }) {
  return <div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Sub-Agent Number</th><th>Terminal Number</th><th>Payer / agency</th><th>Status</th><th>Expected</th><th>Gross collected</th><th>Reversals</th><th>Net collected</th><th>Outstanding</th><th>Open obligations</th><th>Obligations</th><th>Payments</th><th>Last payment</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.id || row.sub_agent_number_id}-${row.payer || row.payer_id}-${index}`}><td>{onHistory ? <button type="button" className="text-link" onClick={() => onHistory(row)}>{row.sub_agent_number}</button> : row.sub_agent_number_snapshot || "Legacy — Sub-Agent Number not assigned"}</td><td>{row.terminal_number || row.terminal_number_snapshot || "Not assigned"}</td><td>{row.payer_name || row.payer_name_snapshot}<small>{row.agency_name || row.agency_name_snapshot}</small></td><td>{row.is_active === undefined ? "Historical totals" : row.is_active ? "Active" : "Inactive"}</td><td>{formatPaymentMoney(row.total_expected)}</td><td>{formatPaymentMoney(row.gross_posted_amount)}</td><td>{formatPaymentMoney(row.reversed_amount)}</td><td>{formatPaymentMoney(row.net_collected_amount)}</td><td>{formatPaymentMoney(row.outstanding_balance)}</td><td>{row.open_obligation_count}</td><td>{row.obligation_count}</td><td>{row.payment_count}</td><td>{row.last_payment_date ? String(row.last_payment_date).slice(0, 10) : "None"}</td></tr>)}</tbody></table></div>;
}

function NumberHistory({ number, payer }) {
  const state = usePaymentPage("payer-payments/", { sub_agent_number: number.id, payer });
  return <section aria-label="Number payment history"><h4>Payment history · {number.sub_agent_number}</h4><div className="payment-table-wrap"><table className="payment-table"><thead><tr><th>Receipt</th><th>Obligation</th><th>Date</th><th>Amount</th><th>Status</th></tr></thead><tbody>{state.rows.map((row) => <tr key={row.id}><td><Link href={`/dashboard/payments/receipts/${row.id}`}>{row.receipt_number}</Link></td><td>{row.obligation_number}</td><td>{String(row.payment_date).slice(0, 10)}</td><td>{formatPaymentMoney(row.amount_received)}</td><td>{row.status}</td></tr>)}</tbody></table></div><PageControls state={state} /></section>;
}

export default function PayerNumberLedger({ payer }) {
  const state = usePaymentPage(`payment-payers/${payer}/numbers/`, {});
  const [selected, setSelected] = useState(null);
  return <section className="panel"><h3>Owned Sub-Agent Numbers</h3><NumberTotalsTable rows={state.rows} onHistory={setSelected} /><PageControls state={state} />{selected ? <NumberHistory key={selected.id} number={selected} payer={payer} /> : null}</section>;
}
