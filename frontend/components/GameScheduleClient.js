"use client";

import { CalendarDays, Check, Edit2, Plus, Power, PowerOff, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import {
  emptyScheduleForm,
  formFromSchedule,
  groupScheduleByWeekday,
  listFromSchedulePayload,
  scheduleMode,
  schedulePayload,
  validateScheduleForm,
  WEEKDAYS,
  withScheduleMode,
} from "../lib/game-schedule-operations";
import { listFromApiPayload } from "../lib/resource-shapes";

function formatTime(value) {
  if (!value) return "";
  const [hourText, minute] = value.split(":");
  const hour = Number(hourText);
  const suffix = hour >= 12 ? "pm" : "am";
  const clockHour = hour % 12 || 12;
  return `${String(clockHour).padStart(2, "0")}:${minute} ${suffix}`;
}

function StatusBadge({ active }) {
  return <span className={`status-pill ${active ? "approved" : "returned"}`}>{active ? "Active" : "Inactive"}</span>;
}

function ModeToggle({ value, onChange }) {
  return (
    <div className="segmented-control" role="group" aria-label="Schedule mode">
      <button type="button" className={!value ? "selected" : ""} onClick={() => onChange(false)}>
        Timed
      </button>
      <button type="button" className={value ? "selected" : ""} onClick={() => onChange(true)}>
        Whole Day
      </button>
    </div>
  );
}

export default function GameScheduleClient({ user }) {
  const canMutate = user.role === "SUPER_ADMIN";
  const [entries, setEntries] = useState([]);
  const [games, setGames] = useState([]);
  const [form, setForm] = useState(emptyScheduleForm());
  const [editingId, setEditingId] = useState("");
  const [state, setState] = useState({ loading: true, saving: false, error: "", success: "" });

  const groups = useMemo(() => groupScheduleByWeekday(entries), [entries]);
  const activeGames = useMemo(() => games.filter((game) => game.is_active !== false), [games]);

  async function loadData() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const [schedulePayloadResult, gamesPayload] = await Promise.all([
        clientRequest(apiPath("/weekly-game-schedules/")),
        clientRequest(apiPath("/games/")),
      ]);
      setEntries(listFromSchedulePayload(schedulePayloadResult));
      setGames(listFromApiPayload(gamesPayload));
      setState((current) => ({ ...current, loading: false }));
    } catch (error) {
      setState({ loading: false, saving: false, error: error.message, success: "" });
    }
  }

  useEffect(() => {
    queueMicrotask(loadData);
  }, []);

  function beginCreate() {
    setEditingId("");
    setForm(emptyScheduleForm());
    setState((current) => ({ ...current, error: "", success: "" }));
  }

  function beginEdit(entry) {
    setEditingId(String(entry.id));
    setForm(formFromSchedule(entry));
    setState((current) => ({ ...current, error: "", success: "" }));
  }

  async function saveSchedule(event) {
    event.preventDefault();
    if (!canMutate) return;
    const error = validateScheduleForm(form);
    if (error) {
      setState((current) => ({ ...current, error, success: "" }));
      return;
    }
    setState((current) => ({ ...current, saving: true, error: "", success: "" }));
    try {
      const path = editingId ? `/weekly-game-schedules/${editingId}/` : "/weekly-game-schedules/";
      await clientRequest(apiPath(path), {
        method: editingId ? "PATCH" : "POST",
        body: JSON.stringify(schedulePayload(form)),
      });
      await loadData();
      const message = editingId ? "Schedule entry updated." : "Schedule entry created.";
      setEditingId("");
      setForm(emptyScheduleForm());
      setState({ loading: false, saving: false, error: "", success: message });
    } catch (error) {
      setState({ loading: false, saving: false, error: JSON.stringify(error.payload || error.message), success: "" });
    }
  }

  async function setActive(entry, active) {
    if (!canMutate) return;
    const action = active ? "activate" : "deactivate";
    if (!window.confirm(`Confirm ${action} for ${entry.game_name} on ${entry.weekday_display}.`)) {
      return;
    }
    try {
      await clientRequest(apiPath(`/weekly-game-schedules/${entry.id}/`), {
        method: active ? "PATCH" : "DELETE",
        body: active ? JSON.stringify({ is_active: true }) : undefined,
      });
      await loadData();
      setState({ loading: false, saving: false, error: "", success: `Schedule entry ${active ? "activated" : "deactivated"}.` });
    } catch (error) {
      setState({ loading: false, saving: false, error: JSON.stringify(error.payload || error.message), success: "" });
    }
  }

  return (
    <div className="page-stack schedule-page">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Weekly Game Schedule</h2>
            <p className="empty-state">Current active entries feed new daily sheet snapshots.</p>
          </div>
          {canMutate ? (
            <button className="secondary-button" type="button" onClick={beginCreate}>
              <Plus size={16} aria-hidden="true" />
              New entry
            </button>
          ) : null}
        </div>
        {state.error ? <p className="form-error">{state.error}</p> : null}
        {state.success ? <p className="form-success">{state.success}</p> : null}
      </section>

      <section className="schedule-layout">
        <div className="schedule-days">
          {groups.map((group) => (
            <section className="panel schedule-day" key={group.value}>
              <div className="panel-heading">
                <h2>{group.label}</h2>
                <span>{group.entries.filter((entry) => entry.is_active).length} active</span>
              </div>
              <div className="table-wrap responsive-table">
                <table className="schedule-table">
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>Game</th>
                      <th>Mode</th>
                      <th>Closing</th>
                      <th>Draw</th>
                      <th>Status</th>
                      {canMutate ? <th>Actions</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {state.loading ? <tr><td colSpan={canMutate ? 7 : 6} className="empty-cell">Loading schedule...</td></tr> : null}
                    {!state.loading && !group.entries.length ? <tr><td colSpan={canMutate ? 7 : 6} className="empty-cell">No schedule entries.</td></tr> : null}
                    {group.entries.map((entry) => (
                      <tr key={entry.id}>
                        <td data-label="Order">{entry.display_order}</td>
                        <td data-label="Game"><strong>{entry.game_name}</strong></td>
                        <td data-label="Mode">{scheduleMode(entry)}</td>
                        <td data-label="Closing">{entry.is_whole_day ? "Whole Day" : formatTime(entry.closing_time)}</td>
                        <td data-label="Draw">{entry.is_whole_day ? "Whole Day" : formatTime(entry.draw_time)}</td>
                        <td data-label="Status"><StatusBadge active={entry.is_active} /></td>
                        {canMutate ? (
                          <td data-label="Actions">
                            <div className="button-row compact">
                              <button className="icon-button" type="button" onClick={() => beginEdit(entry)} aria-label={`Edit ${entry.game_name}`}>
                                <Edit2 size={16} aria-hidden="true" />
                              </button>
                              {entry.is_active ? (
                                <button className="icon-button danger-soft" type="button" onClick={() => setActive(entry, false)} aria-label={`Deactivate ${entry.game_name}`}>
                                  <PowerOff size={16} aria-hidden="true" />
                                </button>
                              ) : (
                                <button className="icon-button success-soft" type="button" onClick={() => setActive(entry, true)} aria-label={`Activate ${entry.game_name}`}>
                                  <Power size={16} aria-hidden="true" />
                                </button>
                              )}
                            </div>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>

        {canMutate ? (
          <form className="panel form-panel schedule-form" onSubmit={saveSchedule}>
            <div className="panel-heading">
              <h2>{editingId ? "Edit Entry" : "Add Entry"}</h2>
              {editingId ? (
                <button className="icon-button" type="button" onClick={beginCreate} aria-label="Cancel edit">
                  <X size={18} aria-hidden="true" />
                </button>
              ) : <CalendarDays size={20} aria-hidden="true" />}
            </div>
            <div className="field-grid single">
              <label className="field-group">Game
                <select required value={form.game} onChange={(event) => setForm({ ...form, game: event.target.value })}>
                  <option value="">Select game</option>
                  {activeGames.map((game) => <option key={game.id} value={game.id}>{game.name}</option>)}
                </select>
              </label>
              <label className="field-group">Weekday
                <select required value={form.weekday} onChange={(event) => setForm({ ...form, weekday: event.target.value })}>
                  {WEEKDAYS.map((weekday) => <option key={weekday.value} value={weekday.value}>{weekday.label}</option>)}
                </select>
              </label>
              <label className="field-group">Display order
                <input type="number" min="1" step="1" required value={form.display_order} onChange={(event) => setForm({ ...form, display_order: event.target.value })} />
              </label>
              <div className="field-group">
                <span>Mode</span>
                <ModeToggle value={form.is_whole_day} onChange={(isWholeDay) => setForm(withScheduleMode(form, isWholeDay))} />
              </div>
              {!form.is_whole_day ? (
                <>
                  <label className="field-group">Closing Time
                    <input type="time" required value={form.closing_time} onChange={(event) => setForm({ ...form, closing_time: event.target.value })} />
                  </label>
                  <label className="field-group">Draw Time
                    <input type="time" required value={form.draw_time} onChange={(event) => setForm({ ...form, draw_time: event.target.value })} />
                  </label>
                </>
              ) : null}
              <label className="switch-row strong">
                <input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />
                Active
              </label>
            </div>
            <button className="primary-button" type="submit" disabled={state.saving}>
              {editingId ? <Save size={16} aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}
              {state.saving ? "Saving..." : editingId ? "Save entry" : "Create entry"}
            </button>
          </form>
        ) : null}
      </section>
    </div>
  );
}
