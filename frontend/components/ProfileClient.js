"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiPath, clientRequest } from "../lib/client-api";

export default function ProfileClient() {
  const router = useRouter();
  const [profile, setProfile] = useState(null);
  const [name, setName] = useState("");
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const submitting = useRef(false);
  useEffect(() => {
    let active = true;
    clientRequest(apiPath("profile/")).then((data) => { if (active) { setProfile(data); setName(data.full_name); } }).catch((error) => { if (active) setErrors({ detail: error.message }); });
    return () => { active = false; };
  }, []);
  async function submit(event, password = false) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setErrors({}); setMessage("");
    try {
      const result = await clientRequest(apiPath(password ? "profile/change-password/" : "profile/"), { method: password ? "POST" : "PATCH", body: JSON.stringify(password ? passwords : { full_name: name }) });
      if (password) {
        setPasswords({ current_password: "", new_password: "", confirm_password: "" });
        setSignedOut(true); setMessage("Password changed. Your sessions have been invalidated. Sign in again to continue.");
        try { await clientRequest("/api/auth/logout", { method: "POST" }); } catch { /* Backend tokens have already been revoked. */ }
      } else { setProfile(result); setName(result.full_name); setMessage("Profile updated successfully."); router.refresh(); }
    } catch (error) { setErrors(error.payload || { detail: error.message }); }
    finally { submitting.current = false; setBusy(false); }
  }
  function feedback(field) { return errors[field] ? <p id={`error-${field}`} role="alert">{Array.isArray(errors[field]) ? errors[field].join(" ") : String(errors[field])}</p> : null; }
  return <section className="audit-profile-page"><h2>My Profile</h2>
    {message && <p role="status">{message}</p>}{feedback("detail")}{feedback("non_field_errors")}
    {signedOut ? <a className="primary-button" href="/login">Sign in again</a> : !profile ? <p>Loading profile…</p> : <>
      <dl className="profile-summary">{[["Display name", profile.full_name], ["Login identifier / email", profile.email], ["Role", profile.role.replaceAll("_", " ")], ["Assigned agencies", profile.agencies.map((agency) => agency.name).join(", ") || "None"], ["Account status", profile.is_active ? "Active" : "Inactive"], ["Last login", profile.last_login ? new Date(profile.last_login).toLocaleString() : "Not available"]].map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
      <p>Email is your login identifier and cannot be changed without a verified-email workflow. Role, assignments and status are managed by an administrator.</p>
      <form className="profile-form" onSubmit={(event) => submit(event)}><h3>Edit profile</h3><p>Your account uses one full-name field rather than separate first and last names.</p><label>Full name<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={255} autoComplete="name" aria-invalid={!!errors.full_name} aria-describedby={errors.full_name ? "error-full_name" : undefined} /></label>{feedback("full_name")}<button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save profile"}</button></form>
      <form className="profile-form" onSubmit={(event) => submit(event, true)}><h3>Change password</h3><p>Changing your password signs out all sessions. You will need to sign in again.</p>
        {[["current_password", "Current password"], ["new_password", "New password"], ["confirm_password", "Confirm new password"]].map(([key, label]) => <div key={key}><label>{label}<input type="password" required autoComplete={key === "current_password" ? "current-password" : "new-password"} value={passwords[key]} onChange={(event) => setPasswords({ ...passwords, [key]: event.target.value })} aria-invalid={!!errors[key]} aria-describedby={errors[key] ? `error-${key}` : undefined} /></label>{feedback(key)}</div>)}
        <button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Change password"}</button>
      </form></>}
  </section>;
}
