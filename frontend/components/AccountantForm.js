"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { clientRequest, apiPath } from "../lib/client-api";
import { saveAccountantWithAssignments } from "../lib/accountant-submit";
import { buildAssignmentRows } from "../lib/resource-shapes";

const flags = [
  ["can_create", "Create"],
  ["can_edit", "Edit"],
  ["can_delete", "Delete"],
  ["can_export", "Export"],
  ["can_view_history", "View history"],
];

export default function AccountantForm({ accountant, agencies, agencyLoadError = "" }) {
  const router = useRouter();
  const editing = Boolean(accountant);
  const [fullName, setFullName] = useState(accountant?.full_name || "");
  const [email, setEmail] = useState(accountant?.email || "");
  const [isActive, setIsActive] = useState(accountant?.is_active ?? true);
  const [password, setPassword] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [assignments, setAssignments] = useState(() => buildAssignmentRows(accountant, agencies));
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const selectedAssignments = useMemo(
    () => assignments.filter((item) => item.selected).map(({ selected, agency_name, ...item }) => item),
    [assignments],
  );

  function updateAssignment(agencyId, changes) {
    setAssignments((items) => items.map((item) => (item.agency === agencyId ? { ...item, ...changes } : item)));
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await saveAccountantWithAssignments({
        editing,
        accountant,
        profile: { fullName, email, password, isActive },
        selectedAssignments,
        agencyLoadError,
      });
      if (result.internalError) {
        setError(result.internalError);
        return;
      }
      if (result.assignmentError) {
        const detail = result.assignmentError.payload ? JSON.stringify(result.assignmentError.payload) : result.assignmentError.message;
        setError(`Profile saved, but agency permissions were not saved. Your selections are still here; retry Save accountant. ${detail}`);
        return;
      }
      setMessage("Accountant saved successfully.");
      if (!editing) {
        router.replace(`/dashboard/accountants/${result.accountantId}`);
      } else {
        router.refresh();
      }
    } catch (err) {
      setError(err.payload ? JSON.stringify(err.payload) : err.message);
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(nextActive) {
    const action = nextActive ? "activate" : "deactivate";
    if (!nextActive && !window.confirm("Deactivate this accountant and block future access?")) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await clientRequest(apiPath(`accountants/${accountant.id}/${action}/`), { method: "POST" });
      setIsActive(updated.is_active);
      setMessage(nextActive ? "Accountant activated." : "Accountant deactivated.");
      router.refresh();
    } catch (err) {
      setError(err.payload ? JSON.stringify(err.payload) : err.message);
    } finally {
      setSaving(false);
    }
  }

  async function submitPasswordReset(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await clientRequest(apiPath(`accountants/${accountant.id}/reset-password/`), {
        method: "POST",
        body: JSON.stringify({ password: resetPassword }),
      });
      setResetPassword("");
      setMessage("Password reset successfully.");
    } catch (err) {
      setError(err.payload ? JSON.stringify(err.payload) : err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="form-grid">
      <form className="panel form-panel" onSubmit={save}>
        <h2>{editing ? "Edit Accountant" : "Create Accountant"}</h2>
        <div className="field-grid">
          <div className="field-group">
            <label htmlFor="full-name">Full name</label>
            <input id="full-name" value={fullName} onChange={(event) => setFullName(event.target.value)} required />
          </div>
          <div className="field-group">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </div>
          {!editing ? (
            <div className="field-group">
              <label htmlFor="initial-password">Initial password</label>
              <input id="initial-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
            </div>
          ) : null}
        </div>

        <label className="switch-row">
          <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
          <span>Active account</span>
        </label>

        <div className="assignment-list">
          <h3>Agency Permissions</h3>
          {agencyLoadError ? <p className="form-error" role="alert">{agencyLoadError}</p> : null}
          {!agencyLoadError && !assignments.length ? <p className="empty-state">No active agencies are available.</p> : null}
          {assignments.map((assignment) => (
            <div className="assignment-card" key={assignment.agency}>
              <label className="switch-row strong">
                <input type="checkbox" checked={assignment.selected} onChange={(event) => updateAssignment(assignment.agency, { selected: event.target.checked })} />
                <span>{assignment.agency_name}</span>
              </label>
              <div className="permission-switches">
                {flags.map(([key, label]) => (
                  <label key={key} className="switch-row">
                    <input
                      type="checkbox"
                      checked={assignment[key]}
                      disabled={!assignment.selected}
                      onChange={(event) => updateAssignment(assignment.agency, { [key]: event.target.checked })}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {message ? <p className="form-success" role="status">{message}</p> : null}

        <div className="button-row">
          <button className="primary-button" type="submit" disabled={saving || (!editing && Boolean(agencyLoadError))}>{saving ? "Saving..." : "Save accountant"}</button>
          {editing && isActive ? <button className="danger-button" type="button" disabled={saving} onClick={() => changeStatus(false)}>Deactivate</button> : null}
          {editing && !isActive ? <button className="secondary-button" type="button" disabled={saving} onClick={() => changeStatus(true)}>Activate</button> : null}
        </div>
      </form>

      {editing ? (
        <form className="panel form-panel" onSubmit={submitPasswordReset}>
          <h2>Reset Password</h2>
          <div className="field-group">
            <label htmlFor="reset-password">New password</label>
            <input id="reset-password" type="password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required />
          </div>
          <button className="secondary-button" type="submit" disabled={saving}>{saving ? "Resetting..." : "Reset password"}</button>
        </form>
      ) : null}
    </div>
  );
}
