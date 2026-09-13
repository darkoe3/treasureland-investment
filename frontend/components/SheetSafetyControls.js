"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPath, clientRequest } from "../lib/client-api";
import { moneyText } from "../lib/phase4-operations";
import { canConfirmSheetAction, sheetControls } from "../lib/sheet-controls";

export default function SheetSafetyControls({ user, sheet, onReset, onDelete, disabled = false }) {
  const router = useRouter();
  const dialog = useRef(null);
  const inFlight = useRef(false);
  const [action, setAction] = useState("reset");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ error: "", success: "" });
  const controls = sheetControls(user, sheet);
  if (user?.role !== "SUPER_ADMIN") return null;
  function open(value) {
    setAction(value); setReason(""); setConfirmed(false);
    setMessage({ error: "", success: "" }); dialog.current.showModal();
  }
  async function submit(event) {
    event.preventDefault();
    if (inFlight.current || !canConfirmSheetAction(reason, confirmed, busy)) return;
    inFlight.current = true; setBusy(true); setMessage({ error: "", success: "" });
    try {
      const result = await clientRequest(apiPath(`/daily-sheets/${sheet.id}/${action === "reset" ? "reset/" : ""}`), {
        method: action === "reset" ? "POST" : "DELETE",
        body: JSON.stringify({ reason: reason.trim(), [action === "reset" ? "confirm_reset" : "confirm_permanent_delete"]: true }),
      });
      if (action === "reset") {
        await onReset(result);
        setMessage({ error: "", success: "Sheet reset. Transaction rows and manual totals cleared." });
      } else if (onDelete) await onDelete();
      else router.push("/dashboard/daily-sheets");
      dialog.current?.close();
    } catch (error) { setMessage({ error: error.message, success: "" }); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <div className="sheet-safety-controls">
    {controls.guidance && <p>{controls.guidance}</p>}
    <div className="sheet-safety-buttons">
      {controls.reset && <button type="button" className="warning-button" disabled={busy || disabled} onClick={() => open("reset")}>Reset sheet</button>}
      {controls.delete && <button type="button" className="danger-button" disabled={busy || disabled} onClick={() => open("delete")}>Delete sheet</button>}
    </div>
    {message.success && <p role="status" className="form-success">{message.success}</p>}
    <dialog ref={dialog} className="sheet-safety-dialog" onCancel={(event) => { if (busy) event.preventDefault(); }}>
      <form onSubmit={submit} className="form-panel">
        <h2>{action === "reset" ? "Reset sheet" : "Permanently delete sheet"}</h2>
        <p>{sheet.agency_name} / {sheet.transaction_date} / {sheet.status}</p>
        <p>{sheet.transaction_count ?? sheet.entered_terminals} transactions / NET Sales {moneyText(sheet.gross_sales)} / To Pay {moneyText(sheet.total_to_pay)}</p>
        <p>{action === "reset" ? "Transaction rows, omissions and manual totals will be removed. The sheet, historical game snapshots and audit history remain." : "Deletion is permanent. This empty Draft sheet will be removed. Its audit history remains."}</p>
        <label className="field-group">Reason<textarea required value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} /></label>
        <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} /> I confirm {action === "reset" ? "this sheet reset" : "permanent deletion"}.</label>
        {message.error && <p role="alert" className="form-error">{message.error}</p>}
        <div className="sheet-safety-buttons">
          <button type="button" className="secondary-button" disabled={busy} onClick={() => dialog.current.close()}>Cancel</button>
          <button type="submit" className={action === "reset" ? "warning-button" : "danger-button"} disabled={!canConfirmSheetAction(reason, confirmed, busy)}>{busy ? "Working..." : action === "reset" ? "Confirm reset" : "Permanently delete"}</button>
        </div>
      </form>
    </dialog>
  </div>;
}
