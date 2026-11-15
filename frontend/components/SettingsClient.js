"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import AccessDenied from "./AccessDenied";

const groups = [
  ["Organisation", [["display_name", "Organisation display name", 160], ["address", "Address", 500], ["telephone", "Telephone", 40], ["contact_email", "Public/contact email", 254]]],
  ["Receipt presentation", [["receipt_heading", "Receipt heading", 120], ["receipt_footer", "Receipt footer message", 500]]],
  ["Regional display", [["timezone", "Timezone", 64], ["date_format", "Date display format", 10]]],
];
const editable = (data) => Object.fromEntries(groups.flatMap(([, fields]) => fields.map(([key]) => [key, data[key]])));

export default function SettingsClient() {
  const [saved, setSaved] = useState(null);
  const [values, setValues] = useState({});
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [denied, setDenied] = useState(false);
  const submitting = useRef(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    clientRequest(apiPath("organisation-settings/")).then((data) => {
      if (active) { setSaved(data); setValues(editable(data)); setErrors({}); setMessage(""); }
    }).catch((error) => { if (active) { setMessage(""); setDenied(error.status === 403); setErrors({ detail: "Could not load settings. Please retry." }); } });
    return () => { active = false; };
  }, [reload]);
  async function save(event) {
    event.preventDefault();
    if (submitting.current || !editing) return;
    submitting.current = true; setBusy(true); setErrors({}); setMessage("");
    try {
      const changes = Object.fromEntries(Object.entries(values).filter(([key, value]) => saved[key] !== value));
      const data = await clientRequest(apiPath("organisation-settings/"), { method: "PATCH", body: JSON.stringify(changes) });
      setSaved(data); setValues(editable(data)); setEditing(false); setMessage("Settings saved successfully.");
    } catch (error) {
      if (error.status === 403) setDenied(true);
      setErrors(error.status === 400 && error.payload ? error.payload : { detail: "Could not save settings. Your changes are preserved. Please retry." });
    } finally { submitting.current = false; setBusy(false); }
  }
  function feedback(key) { return errors[key] ? <p role="alert" id={`settings-error-${key}`}>{[].concat(errors[key]).join(" ")}</p> : null; }
  if (denied) return <AccessDenied />;
  return <section className="settings-page">
    <h2>{saved?.display_name || "Organisation"} settings</h2>
    <p>Manage organisation and receipt presentation. For your account, visit <Link href="/dashboard/profile">My Profile</Link>.</p>
    {message && <p role="status" className="form-success">{message}</p>}{feedback("detail")}{feedback("non_field_errors")}
    {!saved ? <>{errors.detail ? <button onClick={() => setReload(reload + 1)}>Retry</button> : <p role="status">Loading settings…</p>}</> : <>
      <form onSubmit={save} aria-busy={busy}>
        <div className="settings-actions">{editing ? <><button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save settings"}</button><button type="button" disabled={busy} onClick={() => { setValues(editable(saved)); setEditing(false); setErrors({}); setMessage(""); }}>Cancel</button></> : <button type="button" className="primary-button" onClick={() => { setEditing(true); setMessage(""); }}>Edit settings</button>}</div>
        <div className="settings-cards">{groups.map(([title, fields]) => <section className="settings-card" key={title}><h3>{title}</h3>
          {fields.map(([key, label, maxLength]) => {
            const props = { id: `setting-${key}`, value: values[key] || "", disabled: !editing || busy, maxLength, required: ["display_name", "receipt_heading", "timezone", "date_format"].includes(key), onChange: (event) => setValues({ ...values, [key]: event.target.value }), "aria-invalid": !!errors[key], "aria-describedby": errors[key] ? `settings-error-${key}` : undefined };
            return <div key={key}><label htmlFor={props.id}>{label}{key === "date_format" ? <select {...props}>{["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"].map((value) => <option key={value}>{value}</option>)}</select> : ["address", "receipt_footer"].includes(key) ? <textarea {...props} /> : <input {...props} type={key === "contact_email" ? "email" : "text"} />}</label>{feedback(key)}</div>;
          })}
          {title === "Regional display" && <p>Use an IANA timezone such as Africa/Lagos. These preferences format the receipt generation timestamp in its header; transaction dates and schedules remain unchanged.</p>}
          {title === "Receipt presentation" && <p>Downloaded receipts use current organisation header/footer presentation. Historical financial and identity snapshots remain unchanged.</p>}
        </section>)}</div>
      </form>
      <div className="settings-cards">
        <section className="settings-card"><h3>Financial Policy</h3><p>Read-only</p><p>Currency: {saved.financial_policy.currency_name} ({saved.financial_policy.currency})</p><p>Currency symbol: {saved.financial_policy.currency_symbol}</p><p>Current Daily Sheet commission: {Number(saved.financial_policy.commission_rate) * 100}%</p><p>Historical Daily Sheets retain their stored commission snapshots. Financial policy cannot be changed here.</p></section>
        <section className="settings-card"><h3>System Information</h3><p>Read-only</p><p>{saved.system_information.application}</p><p>Settings Version {saved.system_information.settings_version}</p><p>Settings access: Super Admin only</p></section>
      </div>
    </>}
  </section>;
}
