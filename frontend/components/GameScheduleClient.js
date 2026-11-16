"use client";

import { CalendarDays, Check, Edit2, Plus, Power, PowerOff, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiPath, clientRequest } from "../lib/client-api";
import GameCatalogue from "./GameCatalogue";
import {
  categoryLabel,
  emptyScheduleForm,
  formFromSchedule,
  groupScheduleByWeekday,
  listFromSchedulePayload,
  scheduleMode,
  schedulePayload,
  validateScheduleForm,
  validateWeeklySchedule,
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

function emptyHolidayForm() {
  return { holiday_date: "", holiday_name: "", normal_game: "", replacement_game: "", source_date: "", notes: "", is_active: true };
}

function localDateString() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export default function GameScheduleClient({ user }) {
  const canMutate = user.role === "SUPER_ADMIN";
  const [entries, setEntries] = useState([]);
  const [games, setGames] = useState([]);
  const [overrides, setOverrides] = useState([]);
  const [form, setForm] = useState(emptyScheduleForm());
  const [holidayForm, setHolidayForm] = useState(emptyHolidayForm());
  const [holidayEditingId, setHolidayEditingId] = useState("");
  const [holidayChoices, setHolidayChoices] = useState({ normal: [], source: [] });
  const [editingId, setEditingId] = useState("");
  const [state, setState] = useState({ loading: true, saving: false, error: "", success: "" });
  const [activeTab, setActiveTab] = useState("schedule");
  const [showValidation, setShowValidation] = useState(false);

  const groups = useMemo(() => groupScheduleByWeekday(entries), [entries]);
  const activeGames = useMemo(() => games.filter((game) => game.is_active !== false), [games]);
  const selectedGame = games.find((game) => String(game.id) === form.game);
  const activeCountForSelectedDay = entries.filter((entry) => (
    Number(entry.weekday) === Number(form.weekday)
    && entry.is_active
    && entry.game_is_active !== false
  )).length;
  const selectedDayLimit = Number(form.weekday) === 7 ? 6 : 7;
  const addingGhanaGameToFullDay = !editingId
    && form.is_active
    && selectedGame?.name.trim().toLowerCase() === "ghana game"
    && activeCountForSelectedDay >= selectedDayLimit;
  const selectableGames = selectedGame && selectedGame.is_active === false
    ? [...activeGames, selectedGame]
    : activeGames;
  const weeklyValidation = useMemo(() => validateWeeklySchedule(entries, games), [entries, games]);

  async function loadData() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const [schedulePayloadResult, gamesPayload, overridesPayload] = await Promise.all([
        clientRequest(apiPath("/weekly-game-schedules/")),
        clientRequest(apiPath("/games/")),
        clientRequest(apiPath("/holiday-game-overrides/")),
      ]);
      setEntries(listFromSchedulePayload(schedulePayloadResult));
      setGames(listFromApiPayload(gamesPayload));
      setOverrides(listFromSchedulePayload(overridesPayload));
      setState((current) => ({ ...current, loading: false }));
      return true;
    } catch (error) {
      setState({ loading: false, saving: false, error: error.message, success: "" });
      return false;
    }
  }

  useEffect(() => {
    queueMicrotask(loadData);
  }, []);

  function beginCreate(game = null, weekday = "") {
    setEditingId("");
    const empty = emptyScheduleForm();
    const category = game?.category === "GHANA_GAME" ? "GHANA" : game?.category || empty.category;
    const initial = {
      ...empty,
      game: game ? String(game.id) : "",
      weekday: weekday ? String(weekday) : empty.weekday,
      category,
    };
    setForm(game ? withScheduleMode(initial, game.category !== "TIMED") : initial);
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

  async function loadHolidayChoices(target, selectedDate) {
    if (!selectedDate) {
      setHolidayChoices((current) => ({ ...current, [target]: [] }));
      return;
    }
    try {
      const [year, month, day] = selectedDate.split("-").map(Number);
      const weekday = new Date(year, month - 1, day).getDay() || 7;
      const path = `/weekly-game-schedules/?weekday=${weekday}&active=true`;
      const payload = await clientRequest(apiPath(path));
      setHolidayChoices((current) => ({
        ...current,
        [target]: listFromSchedulePayload(payload).filter((entry) => entry.category === "GHANA"),
      }));
    } catch (error) {
      setState((current) => ({ ...current, error: error.message }));
    }
  }

  function changeHolidayField(field, value) {
    setHolidayForm((current) => ({ ...current, [field]: value }));
    if (field === "holiday_date") loadHolidayChoices("normal", value);
    if (field === "source_date") loadHolidayChoices("source", value);
  }

  function beginHolidayEdit(entry) {
    if (!canMutate || !entry.can_edit) return;
    setHolidayEditingId(String(entry.id));
    setHolidayForm({
      holiday_date: entry.holiday_date,
      holiday_name: entry.holiday_name,
      normal_game: String(entry.normal_game),
      replacement_game: String(entry.replacement_game),
      source_date: entry.source_date,
      notes: entry.notes || "",
      is_active: Boolean(entry.is_active),
    });
    loadHolidayChoices("normal", entry.holiday_date);
    loadHolidayChoices("source", entry.source_date);
  }

  function resetHolidayForm() {
    setHolidayEditingId("");
    setHolidayForm(emptyHolidayForm());
    setHolidayChoices({ normal: [], source: [] });
  }

  async function saveHolidayOverride(event) {
    event.preventDefault();
    if (!canMutate) return;
    setState((current) => ({ ...current, saving: true, error: "", success: "" }));
    try {
      const wasEditing = Boolean(holidayEditingId);
      const path = wasEditing ? `/holiday-game-overrides/${holidayEditingId}/` : "/holiday-game-overrides/";
      await clientRequest(apiPath(path), {
        method: wasEditing ? "PATCH" : "POST",
        body: JSON.stringify({
          ...holidayForm,
          normal_game: Number(holidayForm.normal_game),
          replacement_game: Number(holidayForm.replacement_game),
        }),
      });
      resetHolidayForm();
      await loadData();
      setState({ loading: false, saving: false, error: "", success: wasEditing ? "Holiday override updated." : "Holiday override created." });
    } catch (error) {
      setState({ loading: false, saving: false, error: JSON.stringify(error.payload || error.message), success: "" });
    }
  }

  async function setHolidayActive(entry, active) {
    if (!canMutate) return;
    try {
      await clientRequest(apiPath(`/holiday-game-overrides/${entry.id}/`), {
        method: "PATCH",
        body: JSON.stringify({ is_active: active }),
      });
      await loadData();
      setState({ loading: false, saving: false, error: "", success: `Holiday override ${active ? "activated" : "deactivated"}.` });
    } catch (error) {
      setState({ loading: false, saving: false, error: JSON.stringify(error.payload || error.message), success: "" });
    }
  }

  async function cancelHolidayOverride(entry) {
    if (!canMutate) return;
    const reason = window.prompt(`Cancellation reason for ${entry.holiday_name} (${entry.holiday_date})`);
    if (!reason?.trim()) return;
    try {
      await clientRequest(apiPath(`/holiday-game-overrides/${entry.id}/cancel/`), {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      await loadData();
      setState({ loading: false, saving: false, error: "", success: "Holiday override cancelled." });
    } catch (error) {
      setState({ loading: false, saving: false, error: JSON.stringify(error.payload || error.message), success: "" });
    }
  }

  return (
    <div className="page-stack schedule-page">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Game Schedule</h2>
            <p className="empty-state">Manage the catalogue, weekly assignments and holiday overrides. All times use Ghana local time (Africa/Accra). Changes apply to newly created sheets and obligations; existing records keep their saved times.</p>
          </div>
        </div>
        <nav className="game-schedule-tabs" aria-label="Game schedule sections">
          <button type="button" aria-pressed={activeTab === "schedule"} className={activeTab === "schedule" ? "selected" : ""} onClick={() => setActiveTab("schedule")}>Weekly Schedule</button>
          {canMutate ? <button type="button" aria-pressed={activeTab === "games"} className={activeTab === "games" ? "selected" : ""} onClick={() => setActiveTab("games")}>Manage Games</button> : null}
          <button type="button" aria-pressed={activeTab === "holidays"} className={activeTab === "holidays" ? "selected" : ""} onClick={() => setActiveTab("holidays")}>Holiday Overrides</button>
        </nav>
      </section>

      {activeTab === "schedule" ? <>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Weekly Game Schedule</h2>
            <p className="empty-state">Current active entries feed new daily sheet snapshots.</p>
          </div>
          {canMutate ? <button className="secondary-button" type="button" onClick={() => beginCreate()}><Plus size={16} aria-hidden="true" />New entry</button> : null}
        </div>
        {state.error ? <p className="form-error" role="alert">{state.error}</p> : null}
        {state.success ? <p className="form-success" role="status">{state.success}</p> : null}
      </section>
      <section className="panel schedule-validation">
        <div className="panel-heading">
          <div>
            <h3>Weekly schedule validation</h3>
            <p className={weeklyValidation.every((day) => day.ready) ? "form-success" : "form-error"} role="status">
              {weeklyValidation.every((day) => day.ready) ? "Ready for Daily Sheets." : "Work in progress — incomplete schedules cannot be used for Daily Sheets."}
            </p>
          </div>
          <button type="button" className="secondary-button" onClick={() => setShowValidation(true)}>Validate Weekly Schedule</button>
        </div>
        {showValidation ? <ul className="schedule-validation-list" aria-live="polite">
          {weeklyValidation.map((day) => <li key={day.value}><strong>{day.label}:</strong> {day.ready ? "Ready." : day.issues.join(" ")}</li>)}
        </ul> : null}
      </section>
      <section className="schedule-layout">
        <div className="schedule-days">
          {groups.map((group) => (
            <section className="panel schedule-day" key={group.value}>
              <div className="panel-heading">
                <h2>{group.label}</h2>
                <span>{group.entries.filter((entry) => entry.is_active && entry.game_is_active !== false).length}/{group.value === 7 ? 6 : 7} active</span>
              </div>
              {group.entries.filter((entry) => entry.is_active && entry.game_is_active !== false).length !== (group.value === 7 ? 6 : 7) ? (
                <p className="form-error" role="alert">Expected {group.value === 7 ? 6 : 7} active games for {group.label}.</p>
              ) : null}
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
                    {!state.loading && !group.entries.length ? <tr><td colSpan={canMutate ? 7 : 6} className="empty-cell">{canMutate ? <><p>No schedule assignments for this day.</p><button className="secondary-button" type="button" onClick={() => beginCreate(null, group.value)}>Add game to day</button></> : "No schedule assignments for this day."}</td></tr> : null}
                    {group.entries.map((entry) => (
                      <tr key={entry.id}>
                        <td data-label="Order">{entry.display_order}</td>
                        <td data-label="Game"><strong>{entry.game_name}</strong><small className="game-abbreviation">{categoryLabel(entry.category)}</small></td>
                        <td data-label="Mode">{scheduleMode(entry)}</td>
                        <td data-label="Closing">{entry.is_whole_day ? "Whole Day" : formatTime(entry.closing_time)}</td>
                        <td data-label="Draw">{entry.is_whole_day ? "Whole Day" : formatTime(entry.draw_time)}</td>
                        <td data-label="Status"><StatusBadge active={entry.is_active && entry.game_is_active !== false} /></td>
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
                                <button className="icon-button success-soft" type="button" disabled={entry.game_is_active === false} onClick={() => setActive(entry, true)} aria-label={`Activate ${entry.game_name}`}>
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
                <select required value={form.game} onChange={(event) => {
                  const selectedGame = activeGames.find((game) => String(game.id) === event.target.value);
                  if (!selectedGame) {
                    setForm({ ...form, game: "" });
                    return;
                  }
                  const category = selectedGame.category === "GHANA_GAME" ? "GHANA" : selectedGame.category;
                  setForm(withScheduleMode({ ...form, game: event.target.value, category }, selectedGame.category !== "TIMED"));
                }}>
                  <option value="">Select game</option>
                  {selectableGames.map((game) => <option key={game.id} value={game.id}>{game.name}{game.is_active === false ? " (Inactive)" : ""}</option>)}
                </select>
              </label>
              {!activeGames.length ? <p className="form-error">No active games. <button className="secondary-button compact-button" type="button" onClick={() => setActiveTab("games")}>Create the first game</button></p> : null}
              <label className="field-group">Weekday
                <select required value={form.weekday} onChange={(event) => setForm({ ...form, weekday: event.target.value })}>
                  <option value="">Select weekday</option>
                  {WEEKDAYS.map((weekday) => <option key={weekday.value} value={weekday.value}>{weekday.label}</option>)}
                </select>
              </label>
              {addingGhanaGameToFullDay ? <p className="form-error" role="alert">
                This weekday already has {selectedDayLimit} active games. To keep the approved schedule valid, first deactivate the TIMED game you intend to replace; do not remove the Whole Day Ghana or Double Chance entry. No game will be replaced automatically.
              </p> : null}
              <label className="field-group">Display order
                <input type="number" min="1" step="1" required value={form.display_order} onChange={(event) => setForm({ ...form, display_order: event.target.value })} />
              </label>
              <p className="field-group"><strong>Mode:</strong> {form.is_whole_day ? "Whole Day" : "Timed"} (based on the selected game&apos;s category)</p>
              {form.is_whole_day ? <p className="empty-state">Whole Day games have no closing or draw time.</p> : <p className="empty-state">Enter closing and draw times in Ghana local time (Africa/Accra). Draw time must be later on the same day.</p>}
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
            <button className="primary-button" type="submit" disabled={state.saving || addingGhanaGameToFullDay}>
              {editingId ? <Save size={16} aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}
              {state.saving ? "Saving..." : editingId ? "Save entry" : "Create entry"}
            </button>
          </form>
        ) : null}
      </section>
      </> : null}
      {activeTab === "games" && canMutate ? <GameCatalogue games={games} entries={entries} loading={state.loading} onRefresh={loadData} onSchedule={(game) => { beginCreate(game); setActiveTab("schedule"); }} /> : null}
      {activeTab === "holidays" ? <>
      <section className="panel holiday-overrides-panel">
        <div className="panel-heading">
          <div>
            <h2>Holiday Overrides</h2>
            <p className="empty-state">Date-specific Ghana Whole Day replacements; Double Chance and timed games remain available.</p>
          </div>
        </div>
        <div className="table-wrap responsive-table">
          <table className="schedule-table">
            <thead><tr><th>Holiday date</th><th>Holiday</th><th>Normal game</th><th>Game sold</th><th>Source date</th><th>Status</th>{canMutate ? <th>Actions</th> : null}</tr></thead>
            <tbody>
              {!overrides.length ? <tr><td colSpan={canMutate ? 7 : 6} className="empty-cell">No holiday overrides.</td></tr> : null}
              {overrides.map((entry) => (
                <tr key={entry.id}>
                  <td data-label="Holiday date">{entry.holiday_date}</td>
                  <td data-label="Holiday">{entry.holiday_name}</td>
                  <td data-label="Normal game">{entry.normal_game_name}</td>
                  <td data-label="Game sold">{entry.replacement_game_name}</td>
                  <td data-label="Source date">{entry.source_date}</td>
                  <td data-label="Status"><StatusBadge active={entry.is_active} />{entry.cancelled_at ? " Cancelled" : ""}{entry.is_used ? " · Used" : ""}</td>
                  {canMutate ? (
                    <td data-label="Actions"><div className="button-row compact">
                      {entry.can_edit ? <button className="icon-button" type="button" onClick={() => beginHolidayEdit(entry)} aria-label={`Edit ${entry.holiday_name}`}><Edit2 size={16} aria-hidden="true" /></button> : null}
                      {!entry.cancelled_at ? <button className={`icon-button ${entry.is_active ? "danger-soft" : "success-soft"}`} type="button" onClick={() => setHolidayActive(entry, !entry.is_active)} aria-label={`${entry.is_active ? "Deactivate" : "Activate"} ${entry.holiday_name}`}>{entry.is_active ? <PowerOff size={16} aria-hidden="true" /> : <Power size={16} aria-hidden="true" />}</button> : null}
                      {!entry.cancelled_at ? <button className="secondary-button compact-button" type="button" onClick={() => cancelHolidayOverride(entry)}>Cancel</button> : null}
                    </div></td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canMutate ? (
          <form className="form-panel holiday-override-form" onSubmit={saveHolidayOverride}>
            <div className="panel-heading"><h3>{holidayEditingId ? "Edit Holiday Override" : "Add Holiday Override"}</h3>{holidayEditingId ? <button className="icon-button" type="button" onClick={resetHolidayForm} aria-label="Cancel edit"><X size={18} /></button> : null}</div>
            <div className="field-grid">
              <label className="field-group">Holiday date<input type="date" required value={holidayForm.holiday_date} onChange={(event) => changeHolidayField("holiday_date", event.target.value)} /></label>
              <label className="field-group">Holiday name<input required maxLength="160" value={holidayForm.holiday_name} onChange={(event) => changeHolidayField("holiday_name", event.target.value)} /></label>
              <label className="field-group">Normal scheduled Ghana game<select required value={holidayForm.normal_game} onChange={(event) => changeHolidayField("normal_game", event.target.value)}><option value="">Select game</option>{holidayChoices.normal.map((game) => <option key={game.game} value={game.game}>{game.game_name}</option>)}</select></label>
              <label className="field-group">Source date<input type="date" required max={localDateString()} value={holidayForm.source_date} onChange={(event) => changeHolidayField("source_date", event.target.value)} /></label>
              <label className="field-group">Previous Ghana game<select required value={holidayForm.replacement_game} onChange={(event) => changeHolidayField("replacement_game", event.target.value)}><option value="">Select game from source date</option>{holidayChoices.source.map((game) => <option key={game.game} value={game.game}>{game.game_name}</option>)}</select></label>
              <label className="field-group">Notes<textarea value={holidayForm.notes} onChange={(event) => changeHolidayField("notes", event.target.value)} rows="2" /></label>
              <label className="switch-row strong"><input type="checkbox" checked={holidayForm.is_active} onChange={(event) => changeHolidayField("is_active", event.target.checked)} />Active</label>
            </div>
            <button className="primary-button" type="submit" disabled={state.saving || !holidayChoices.normal.length || !holidayChoices.source.length}><Save size={16} aria-hidden="true" />{state.saving ? "Saving..." : holidayEditingId ? "Save override" : "Create override"}</button>
          </form>
        ) : null}
      </section>
      </> : null}
    </div>
  );
}
