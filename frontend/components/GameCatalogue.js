"use client";

import { useMemo, useRef, useState } from "react";
import { Edit2, Power, PowerOff, Plus, Save, X } from "lucide-react";
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
  return [message, affected.length ? `Affected weekdays: ${affected.join(", ")}.` : ""].filter(Boolean).join(" ") || fallback;
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

export default function GameCatalogue({ games, entries, onRefresh, onSchedule, loading = false }) {
  const [form, setForm] = useState(emptyForm());
  const [editingId, setEditingId] = useState("");
  const [formOpen, setFormOpen] = useState(false);
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

  function startEdit(game) {
    setEditingId(String(game.id));
    setForm({
      name: game.name,
      category: isGhanaGame(game.name) ? "TIMED" : game.category,
      is_active: Boolean(game.is_active),
    });
    setFormOpen(true);
    setErrors({});
    setSuccess("");
  }

  function closeForm() {
    setFormOpen(false);
    setEditingId("");
    setForm(emptyForm());
    setErrors({});
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
              <thead><tr><th>Game</th><th>Category</th><th>Status</th><th>Active weekdays</th><th>Updated</th><th>Actions</th></tr></thead>
              <tbody>{visibleGames.map((game) => {
                const weekdays = affectedWeekdays(game, entries);
                return <tr key={game.id}>
                  <td data-label="Game"><strong>{game.name}</strong><small>{game.created_at ? `Created ${new Date(game.created_at).toLocaleDateString()}` : ""}</small></td>
                  <td data-label="Category">{categories.find((category) => category.value === game.category)?.label || game.category}</td>
                  <td data-label="Status"><span className={`status-pill ${game.is_active ? "approved" : "returned"}`}>{game.is_active ? "Active" : "Inactive"}</span></td>
                  <td data-label="Active weekdays">{weekdays.length ? weekdays.join(", ") : "None"}</td>
                  <td data-label="Updated">{game.updated_at ? new Date(game.updated_at).toLocaleDateString() : "—"}</td>
                  <td data-label="Actions"><div className="button-row compact">
                    <button className="icon-button" type="button" disabled={saving} onClick={() => startEdit(game)} aria-label={`Edit ${game.name}`}><Edit2 size={16} aria-hidden="true" /></button>
                    <button className={`icon-button ${game.is_active ? "danger-soft" : "success-soft"}`} type="button" disabled={saving} onClick={() => setGameActive(game, !game.is_active)} aria-label={`${game.is_active ? "Deactivate" : "Reactivate"} ${game.name}`}>{game.is_active ? <PowerOff size={16} aria-hidden="true" /> : <Power size={16} aria-hidden="true" />}</button>
                    <button className="secondary-button compact-button" type="button" disabled={!game.is_active} onClick={() => onSchedule(game)}>Schedule</button>
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
