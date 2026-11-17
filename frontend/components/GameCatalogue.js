"use client";

import { useMemo, useRef, useState } from "react";
import { CalendarDays, Edit2, Power, PowerOff, Plus, Save, X } from "lucide-react";
import { apiPath, clientRequest } from "../lib/client-api";
import { WEEKDAYS } from "../lib/game-schedule-operations";

const categories = [
  { value: "TIMED", label: "TIMED — Timed" },
  { value: "GHANA", label: "GHANA — Whole Day" },
  { value: "DOUBLE_CHANCE", label: "DOUBLE_CHANCE — Double Chance" },
];

function isGhanaGame(name) {
  return name.trim().toLowerCase() === "ghana game";
}

function emptyForm() {
  return { name: "", category: "TIMED", is_active: true };
}

function errorText(value) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(errorText).filter(Boolean).join(" ");
  return "";
}

function backendError(payload, fallback) {
  const message = errorText(payload.detail || payload.non_field_errors || payload.is_active || payload.weekday);
  const affected = Array.isArray(payload.affected_weekdays)
    ? payload.affected_weekdays.filter((day) => typeof day === "string")
    : [];
  const guidance = message.includes("schedule assignments to its current category")
    ? "Open Edit schedule to correct the assignments and activate the game in one operation."
    : "";
  return [message, guidance, affected.length ? `Affected weekdays: ${affected.join(", ")}.` : ""].filter(Boolean).join(" ") || fallback;
}

function affectedWeekdays(game, entries) {
  const active = new Set(entries
    .filter((entry) => String(entry.game) === String(game.id) && entry.is_active && entry.game_is_active !== false)
    .map((entry) => Number(entry.weekday)));
  return WEEKDAYS.filter((day) => active.has(day.value)).map((day) => day.label);
}

function confirmDeactivation(game, weekdays) {
  if (!weekdays.length) return true;
  return window.confirm(`Deactivating ${game.name} removes it from the effective schedule on ${weekdays.join(", ")}. Those days may need replacement games before they are ready for Daily Sheets. Continue?`);
}

function GameErrors({ errors, field }) {
  return errors[field] ? <p className="form-error" role="alert">{errors[field]}</p> : null;
}

export default function GameCatalogue({ games, entries, onRefresh, loading = false }) {
  const [form, setForm] = useState(emptyForm());
  const [editingId, setEditingId] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [connectedGame, setConnectedGame] = useState(null);
  const [connectedForm, setConnectedForm] = useState(null);
  const [connectedErrors, setConnectedErrors] = useState({});
  const [connectedSaving, setConnectedSaving] = useState(false);
  const [connectedFocus, setConnectedFocus] = useState("game");
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [success, setSuccess] = useState("");
  const submitting = useRef(false);
  const visibleGames = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return [...games]
      .filter((game) => !query || `${game.name} ${game.category}`.toLocaleLowerCase().includes(query))
      .sort((left, right) => left.name.localeCompare(right.name));
  }, [games, search]);

  function startCreate() {
    closeConnectedEditor();
    setEditingId("");
    setForm(emptyForm());
    setFormOpen(true);
    setErrors({});
    setSuccess("");
  }

  function startGhanaGame() {
    startCreate();
    setForm({ name: "Ghana Game", category: "TIMED", is_active: true });
  }

  function startEdit(game, focus = "game") {
    setFormOpen(false);
    setEditingId("");
    setConnectedGame(game);
    setConnectedFocus(focus);
    setConnectedForm({
      name: game.name,
      category: game.category,
      is_active: Boolean(game.is_active),
      confirmClearTimes: false,
      assignments: entries
        .filter((entry) => String(entry.game) === String(game.id))
        .map((entry) => ({
          id: Number(entry.id),
          weekday: Number(entry.weekday),
          display_order: String(entry.display_order),
          is_active: Boolean(entry.is_active),
          closing_time: entry.closing_time || "",
          draw_time: entry.draw_time || "",
          replace_schedule_id: "",
        })),
    });
    setConnectedErrors({});
    setErrors({});
    setSuccess("");
  }

  function closeForm() {
    setFormOpen(false);
    setEditingId("");
    setForm(emptyForm());
    setErrors({});
  }

  function closeConnectedEditor() {
    setConnectedGame(null);
    setConnectedForm(null);
    setConnectedErrors({});
  }

  function changeConnectedCategory(category) {
    if (!connectedForm || category === connectedForm.category) return;
    const clearingTimes = category !== "TIMED"
      && connectedForm.assignments.some((assignment) => assignment.closing_time || assignment.draw_time);
    if (clearingTimes && !window.confirm(
      `Changing ${connectedGame.name} to ${category} will clear the closing and draw times on ${connectedForm.assignments.map((assignment) => WEEKDAYS.find((day) => day.value === assignment.weekday)?.label).join(", ")}. Continue?`,
    )) return;
    setConnectedForm({
      ...connectedForm,
      category,
      confirmClearTimes: connectedForm.confirmClearTimes || clearingTimes,
      assignments: category === "TIMED" ? connectedForm.assignments : connectedForm.assignments.map((assignment) => ({
        ...assignment,
        closing_time: "",
        draw_time: "",
      })),
    });
    setConnectedErrors({});
  }

  function updateAssignment(index, changes) {
    setConnectedForm((current) => ({
      ...current,
      assignments: current.assignments.map((assignment, assignmentIndex) => (
        assignmentIndex === index ? { ...assignment, ...changes } : assignment
      )),
    }));
    setConnectedErrors({});
  }

  function addWeekdayAssignment() {
    const available = WEEKDAYS.find((day) => !connectedForm.assignments.some((assignment) => assignment.weekday === day.value));
    if (!available) return;
    setConnectedForm({
      ...connectedForm,
      assignments: [...connectedForm.assignments, {
        weekday: available.value,
        display_order: "1",
        is_active: false,
        closing_time: "",
        draw_time: "",
        replace_schedule_id: "",
      }],
    });
  }

  function connectedErrorFor(assignment, index) {
    return connectedErrors.assignments?.[index]
      || connectedErrors.weekdays?.[assignment.weekday]
      || "";
  }

  function connectedErrorMessage(payload, fallback) {
    const messages = [];
    const details = { weekdays: {}, assignments: {} };
    if (payload.detail) messages.push(errorText(payload.detail));
    for (const conflict of payload.weekday_conflicts || []) {
      details.weekdays[conflict.weekday] = (conflict.errors || []).map((item) => item.message || String(item)).join(" ");
      messages.push(details.weekdays[conflict.weekday]);
    }
    if (Array.isArray(payload.assignments)) {
      payload.assignments.forEach((item, index) => {
        const fields = item.errors || {};
        details.assignments[index] = Object.values(fields).map(errorText).join(" ");
        if (item.weekday && details.assignments[index]) {
          details.weekdays[item.weekday] = details.assignments[index];
        }
      });
    } else if (payload.assignments) {
      messages.push(errorText(payload.assignments));
    }
    for (const field of ["name", "category", "is_active", "confirm_clear_times"]) {
      if (payload[field]) {
        details[field] = errorText(payload[field]);
        messages.push(details[field]);
      }
    }
    if (!messages.length) messages.push(fallback);
    return { message: messages.join(" "), details };
  }

  async function saveConnectedGame(event) {
    event.preventDefault();
    if (submitting.current || !connectedGame || !connectedForm) return;
    const clientErrors = {};
    if (!connectedForm.name.trim()) clientErrors.name = "Game name is required.";
    const assignmentErrors = {};
    connectedForm.assignments.forEach((assignment, index) => {
      if (!/^[1-9]\d*$/.test(assignment.display_order)) {
        assignmentErrors[index] = "Display order must be a positive whole number.";
      } else if (connectedForm.category === "TIMED" && (!assignment.closing_time || !assignment.draw_time)) {
        assignmentErrors[index] = "Enter explicit closing and draw times for this Timed assignment.";
      } else if (connectedForm.category === "TIMED" && assignment.draw_time <= assignment.closing_time) {
        assignmentErrors[index] = "Draw time must be later than closing time in Africa/Accra.";
      }
    });
    if (Object.keys(assignmentErrors).length) clientErrors.assignments = assignmentErrors;
    if (Object.keys(clientErrors).length) {
      setConnectedErrors(clientErrors);
      return;
    }
    const activeWeekdays = affectedWeekdays(connectedGame, entries);
    if (connectedGame.is_active && !connectedForm.is_active && !confirmDeactivation(connectedGame, activeWeekdays)) return;
    submitting.current = true;
    setConnectedSaving(true);
    setConnectedErrors({});
    setSuccess("");
    try {
      await clientRequest(apiPath(`/games/${connectedGame.id}/edit-schedule/`), {
        method: "POST",
        body: JSON.stringify({
          name: connectedForm.name.trim(),
          category: connectedForm.category,
          is_active: connectedForm.is_active,
          confirm_clear_times: connectedForm.confirmClearTimes,
          confirm_deactivation: connectedGame.is_active && !connectedForm.is_active,
          assignments: connectedForm.assignments.map((assignment) => ({
            ...(assignment.id ? { id: assignment.id } : {}),
            weekday: Number(assignment.weekday),
            display_order: Number(assignment.display_order),
            is_active: Boolean(assignment.is_active),
            closing_time: assignment.closing_time || null,
            draw_time: assignment.draw_time || null,
            replace_schedule_id: assignment.replace_schedule_id ? Number(assignment.replace_schedule_id) : null,
          })),
        }),
      });
      const refreshed = await onRefresh();
      closeConnectedEditor();
      setSuccess(refreshed === false
        ? "Changes were saved, but the catalogue could not refresh. Reload to see the latest data."
        : "Game and schedule assignments saved.");
    } catch (error) {
      const parsed = connectedErrorMessage(error.payload || {}, error.message || "Could not save game and schedule.");
      setConnectedErrors(parsed.details);
      setConnectedErrors((current) => ({ ...current, detail: parsed.message }));
    } finally {
      submitting.current = false;
      setConnectedSaving(false);
    }
  }

  async function saveGame(event) {
    event.preventDefault();
    if (submitting.current) return;
    const name = form.name.trim();
    if (!name) {
      setErrors({ name: "Game name is required." });
      setSuccess("");
      return;
    }
    const currentGame = games.find((game) => String(game.id) === editingId);
    const deactivatedWeekdays = currentGame?.is_active && !form.is_active ? affectedWeekdays(currentGame, entries) : [];
    if (deactivatedWeekdays.length && !confirmDeactivation(currentGame, deactivatedWeekdays)) return;

    submitting.current = true;
    setSaving(true);
    setErrors({});
    setSuccess("");
    try {
      const path = editingId ? `/games/${editingId}/` : "/games/";
      await clientRequest(apiPath(path), {
        method: editingId ? "PATCH" : "POST",
        body: JSON.stringify({
          ...form,
          name,
          ...(deactivatedWeekdays.length ? { confirm_deactivation: true } : {}),
        }),
      });
      const refreshed = await onRefresh();
      const message = editingId ? "Game updated successfully." : "Game created successfully.";
      setEditingId("");
      setForm(emptyForm());
      setFormOpen(false);
      setErrors(refreshed === false ? { detail: "The change was saved, but the catalogue could not refresh. Reload the page to see the latest data." } : {});
      setSuccess(message);
    } catch (error) {
      const payload = error.payload || {};
      setErrors({
        name: errorText(payload.name),
        category: errorText(payload.category),
        detail: backendError(payload, error.message || "Could not save game."),
      });
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  async function setGameActive(game, active) {
    if (submitting.current) return;
    const weekdays = affectedWeekdays(game, entries);
    if (!active && !confirmDeactivation(game, weekdays)) return;
    submitting.current = true;
    setSaving(true);
    setErrors({});
    setSuccess("");
    try {
      await clientRequest(apiPath(`/games/${game.id}/`), {
        method: "PATCH",
        body: JSON.stringify({ is_active: active, ...(active ? {} : { confirm_deactivation: true }) }),
      });
      const refreshed = await onRefresh();
      setSuccess(`Game ${active ? "reactivated" : "deactivated"} successfully.`);
      if (refreshed === false) setErrors({ detail: "The change was saved, but the catalogue could not refresh. Reload the page to see the latest data." });
    } catch (error) {
      const payload = error.payload || {};
      setErrors({ detail: backendError(payload, error.message || "Could not update game status.") });
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="page-stack game-catalogue">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Manage Games</h2>
            <p className="empty-state">Create the catalogue before assigning games to weekdays. Games with historical records are deactivated, never deleted.</p>
          </div>
          {!formOpen ? <div className="button-row">
            {!games.some((game) => game.name.trim().toLowerCase() === "ghana game") ? <button className="secondary-button" type="button" disabled={loading} onClick={startGhanaGame}><Plus size={16} aria-hidden="true" />Add Ghana Game</button> : null}
            <button className="primary-button" type="button" disabled={loading} onClick={startCreate}><Plus size={16} aria-hidden="true" />Create game</button>
          </div> : null}
        </div>
        {success ? <p className="form-success" role="status">{success}</p> : null}
        <GameErrors errors={errors} field="detail" />
      </section>

      {formOpen ? <section className="panel game-catalogue-editor">
        <div className="panel-heading"><h3>{editingId ? "Edit game" : "Create game"}</h3><button className="icon-button" type="button" onClick={closeForm} aria-label="Close game form"><X size={18} aria-hidden="true" /></button></div>
        <form className="game-catalogue-form" onSubmit={saveGame} aria-busy={saving}>
          {isGhanaGame(form.name) ? <p className="empty-state">Ghana Game is a Timed game, not the Whole Day Ghana category. After saving, choose Schedule to select a weekday and enter closing and draw times in Africa/Accra. No weekdays or times are assigned automatically.</p> : null}
          <label className="field-group">Game name
            <input maxLength="120" required value={form.name} disabled={saving} onChange={(event) => {
              const name = event.target.value;
              setForm({ ...form, name, ...(isGhanaGame(name) ? { category: "TIMED" } : {}) });
              setErrors({});
            }} />
            <GameErrors errors={errors} field="name" />
          </label>
          <label className="field-group">Category
            <select value={form.category} disabled={saving || isGhanaGame(form.name)} onChange={(event) => { setForm({ ...form, category: event.target.value }); setErrors({}); }}>
              {categories.map((category) => <option key={category.value} value={category.value}>{category.label}</option>)}
            </select>
            <GameErrors errors={errors} field="category" />
          </label>
          <label className="switch-row strong"><input type="checkbox" checked={form.is_active} disabled={saving} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />Active</label>
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={saving}>{saving ? "Saving game…" : <><Save size={16} aria-hidden="true" />{editingId ? "Save game" : "Create game"}</>}</button>
            <button className="secondary-button" type="button" disabled={saving} onClick={closeForm}>Cancel</button>
          </div>
        </form>
      </section> : null}

      {connectedGame && connectedForm ? <section className="panel game-connected-editor" data-focus={connectedFocus}>
        <div className="panel-heading">
          <div>
            <h3>{connectedFocus === "schedule" ? `Edit schedule — ${connectedGame.name}` : `Edit game — ${connectedGame.name}`}</h3>
            <p className="empty-state">Game details and every active or inactive weekday assignment are saved together. Times use Africa/Accra.</p>
          </div>
          <button className="secondary-button" type="button" disabled={connectedSaving} onClick={closeConnectedEditor}>Close editor</button>
        </div>
        {connectedErrors.detail ? <p className="form-error" role="alert">{connectedErrors.detail}</p> : null}
        <form className="game-connected-form" onSubmit={saveConnectedGame} aria-busy={connectedSaving}>
          <div className="game-connected-fields">
            <label className="field-group">Game name
              <input maxLength="120" value={connectedForm.name} disabled={connectedSaving} onChange={(event) => {
                setConnectedForm({ ...connectedForm, name: event.target.value });
                setConnectedErrors({});
              }} />
              <GameErrors errors={connectedErrors} field="name" />
            </label>
            <label className="field-group">Category
              <select value={connectedForm.category} disabled={connectedSaving || isGhanaGame(connectedForm.name)} onChange={(event) => changeConnectedCategory(event.target.value)}>
                {categories.map((category) => <option key={category.value} value={category.value}>{category.label}</option>)}
              </select>
              <GameErrors errors={connectedErrors} field="category" />
            </label>
            <label className="switch-row strong">
              <input type="checkbox" checked={connectedForm.is_active} disabled={connectedSaving} onChange={(event) => setConnectedForm({ ...connectedForm, is_active: event.target.checked })} />
              Active game
            </label>
          </div>
          {isGhanaGame(connectedForm.name) ? <p className="empty-state">Ghana Game must use the TIMED category.</p> : null}
          {connectedForm.category !== connectedGame.category ? <p className="empty-state">
            Changing category will update the listed assignments together. {connectedForm.category === "TIMED"
              ? "Enter explicit closing and draw times for every assignment; none are filled in automatically."
              : "Whole Day assignments have no times."}
          </p> : null}
          {connectedForm.category !== "TIMED" && connectedForm.assignments.some((assignment) => assignment.closing_time || assignment.draw_time) ? <label className="switch-row">
            <input type="checkbox" checked={connectedForm.confirmClearTimes} disabled={connectedSaving} onChange={(event) => setConnectedForm({ ...connectedForm, confirmClearTimes: event.target.checked })} />
            Confirm clearing the current times from {connectedForm.assignments.map((assignment) => WEEKDAYS.find((day) => day.value === assignment.weekday)?.label).filter(Boolean).join(", ")}.
          </label> : null}
          <div className="game-assignment-heading">
            <div><h4>Weekday assignments</h4><p className="empty-state">Inactive assignments are retained and shown here; activate only when each weekday is ready.</p></div>
            <button className="secondary-button" type="button" disabled={connectedSaving || connectedForm.assignments.length >= WEEKDAYS.length} onClick={addWeekdayAssignment}>Add weekday</button>
          </div>
          {!connectedForm.assignments.length ? <p className="empty-state">No weekday assignments yet. Add a weekday to configure its schedule.</p> : null}
          <div className="game-assignment-list">
            {connectedForm.assignments.map((assignment, index) => {
              const weekday = WEEKDAYS.find((day) => day.value === Number(assignment.weekday));
              const existingEntry = entries.find((entry) => String(entry.id) === String(assignment.id));
              const mismatchedCategory = existingEntry && existingEntry.category !== connectedForm.category;
              const replacements = entries.filter((entry) => (
                Number(entry.weekday) === Number(assignment.weekday)
                && String(entry.game) !== String(connectedGame.id)
                && entry.is_active
                && entry.game_is_active !== false
                && entry.category === connectedForm.category
              ));
              const rowError = connectedErrorFor(assignment, index);
              const assignmentStatus = existingEntry
                ? `${existingEntry.is_active ? "Active assignment" : "Inactive assignment"}${existingEntry.game_is_active === false ? " — game inactive" : ""}`
                : "Inactive draft assignment";
              return <fieldset className="game-assignment" key={assignment.id || `new-${index}`}>
                <legend>{weekday?.label || "Weekday"} — {assignmentStatus}</legend>
                <div className="game-assignment-fields">
                  <label className="field-group">Weekday
                    <select value={assignment.weekday} disabled={connectedSaving} onChange={(event) => updateAssignment(index, { weekday: Number(event.target.value), replace_schedule_id: "" })}>
                      {WEEKDAYS.map((day) => <option key={day.value} value={day.value}>{day.label}</option>)}
                    </select>
                  </label>
                  <label className="field-group">Display order
                    <input type="number" min="1" step="1" value={assignment.display_order} disabled={connectedSaving} onChange={(event) => updateAssignment(index, { display_order: event.target.value })} />
                  </label>
                  <label className="switch-row">
                    <input type="checkbox" checked={assignment.is_active} disabled={connectedSaving} onChange={(event) => updateAssignment(index, { is_active: event.target.checked, replace_schedule_id: "" })} />
                    Active assignment
                  </label>
                </div>
                {mismatchedCategory ? <p className="form-error">Currently {existingEntry.category}; it will be changed to {connectedForm.category} with this save.</p> : null}
                {connectedForm.category === "TIMED" ? <div className="game-assignment-times">
                  <label className="field-group">Closing time
                    <input type="time" value={assignment.closing_time} disabled={connectedSaving} onChange={(event) => updateAssignment(index, { closing_time: event.target.value })} />
                  </label>
                  <label className="field-group">Draw time
                    <input type="time" value={assignment.draw_time} disabled={connectedSaving} onChange={(event) => updateAssignment(index, { draw_time: event.target.value })} />
                  </label>
                </div> : <p className="empty-state">Whole Day — closing and draw times are cleared.</p>}
                {assignment.is_active && connectedForm.is_active && replacements.length ? <label className="field-group">Replace an active assignment (optional)
                  <select value={assignment.replace_schedule_id} disabled={connectedSaving} onChange={(event) => updateAssignment(index, { replace_schedule_id: event.target.value })}>
                    <option value="">No replacement</option>
                    {replacements.map((entry) => <option key={entry.id} value={entry.id}>{entry.game_name} — order {entry.display_order}</option>)}
                  </select>
                  <small>Selecting a replacement deactivates that assignment in the same transaction. Nothing is replaced automatically.</small>
                </label> : null}
                {rowError ? <p className="form-error" role="alert">{rowError}</p> : null}
              </fieldset>;
            })}
          </div>
          <div className="button-row">
            <button className="primary-button" type="submit" disabled={connectedSaving}>
              <Save size={16} aria-hidden="true" />
              {connectedSaving ? "Saving game and schedule…" : connectedForm.is_active
                ? (connectedGame.is_active ? "Save active schedule" : "Save and activate")
                : "Save inactive draft"}
            </button>
            <button className="secondary-button" type="button" disabled={connectedSaving} onClick={closeConnectedEditor}>Cancel</button>
          </div>
        </form>
      </section> : null}

      <section className="panel">
        <div className="panel-heading">
          <div><h3>Game Catalogue</h3><p className="empty-state">{games.length} {games.length === 1 ? "game" : "games"}</p></div>
          {games.length ? <label className="game-catalogue-search">Search games<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></label> : null}
        </div>
        {loading ? <p className="empty-state" role="status">Loading games...</p> : !games.length ? (
          <div className="game-catalogue-empty">
            <p>No games have been created.</p>
            <button className="primary-button" type="button" onClick={startCreate}><Plus size={16} aria-hidden="true" />Create first game</button>
          </div>
        ) : !visibleGames.length ? <p className="empty-state">No games match this search.</p> : (
          <div className="table-wrap responsive-table">
            <table className="schedule-table game-catalogue-table">
              <thead><tr><th>Game</th><th>Category</th><th>Status</th><th>Schedule assignments</th><th>Updated</th><th>Actions</th></tr></thead>
              <tbody>{visibleGames.map((game) => {
                const weekdays = affectedWeekdays(game, entries);
                const assignments = entries.filter((entry) => String(entry.game) === String(game.id));
                return <tr key={game.id}>
                  <td data-label="Game"><strong>{game.name}</strong><small>{game.created_at ? `Created ${new Date(game.created_at).toLocaleDateString()}` : ""}</small></td>
                  <td data-label="Category">{categories.find((category) => category.value === game.category)?.label || game.category}</td>
                  <td data-label="Status"><span className={`status-pill ${game.is_active ? "approved" : "returned"}`}>{game.is_active ? "Active" : "Inactive"}</span></td>
                  <td data-label="Schedule assignments">{assignments.length ? assignments.map((entry) => `${entry.weekday_display || WEEKDAYS.find((day) => day.value === Number(entry.weekday))?.label || "Weekday"} (${entry.is_active && game.is_active ? "Active" : "Inactive"})`).join(", ") : "None"}</td>
                  <td data-label="Updated">{game.updated_at ? new Date(game.updated_at).toLocaleDateString() : "—"}</td>
                  <td data-label="Actions"><div className="button-row compact">
                    <button className="secondary-button compact-button" type="button" disabled={saving || connectedSaving} onClick={() => startEdit(game, "game")}><Edit2 size={16} aria-hidden="true" />Edit game</button>
                    <button className="secondary-button compact-button" type="button" disabled={saving || connectedSaving} onClick={() => startEdit(game, "schedule")}><CalendarDays size={16} aria-hidden="true" />Edit schedule</button>
                    <button className={`secondary-button compact-button ${game.is_active ? "danger-soft" : "success-soft"}`} type="button" aria-label={`${game.is_active ? "Deactivate" : "Activate"} ${game.name}`} disabled={saving || connectedSaving} onClick={() => setGameActive(game, !game.is_active)}>{game.is_active ? <PowerOff size={16} aria-hidden="true" /> : <Power size={16} aria-hidden="true" />}{game.is_active ? "Deactivate" : "Activate"}</button>
                  </div></td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
