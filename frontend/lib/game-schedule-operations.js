export const WEEKDAYS = [
  { value: 1, label: "Monday" },
  { value: 2, label: "Tuesday" },
  { value: 3, label: "Wednesday" },
  { value: 4, label: "Thursday" },
  { value: 5, label: "Friday" },
  { value: 6, label: "Saturday" },
  { value: 7, label: "Sunday" },
];

export function scheduleMode(entry) {
  return entry?.is_whole_day ? "Whole Day" : "Timed";
}

export function listFromSchedulePayload(payload) {
  return Array.isArray(payload) ? payload : payload?.results || [];
}

export function groupScheduleByWeekday(entries = []) {
  const groups = new Map(WEEKDAYS.map((weekday) => [weekday.value, { ...weekday, entries: [] }]));
  for (const entry of entries) {
    const weekday = Number(entry.weekday);
    if (groups.has(weekday)) {
      groups.get(weekday).entries.push(entry);
    }
  }
  return Array.from(groups.values()).map((group) => ({
    ...group,
    entries: group.entries.sort((a, b) => Number(a.display_order) - Number(b.display_order) || Number(a.id) - Number(b.id)),
  }));
}

export function emptyScheduleForm() {
  return {
    id: "",
    game: "",
    weekday: "1",
    display_order: "1",
    is_whole_day: false,
    closing_time: "",
    draw_time: "",
    is_active: true,
  };
}

export function formFromSchedule(entry) {
  return {
    id: String(entry.id),
    game: String(entry.game),
    weekday: String(entry.weekday),
    display_order: String(entry.display_order),
    is_whole_day: Boolean(entry.is_whole_day),
    closing_time: entry.closing_time || "",
    draw_time: entry.draw_time || "",
    is_active: Boolean(entry.is_active),
  };
}

export function withScheduleMode(form, isWholeDay) {
  return {
    ...form,
    is_whole_day: isWholeDay,
    closing_time: isWholeDay ? "" : form.closing_time,
    draw_time: isWholeDay ? "" : form.draw_time,
  };
}

export function validateScheduleForm(form) {
  if (!/^\d+$/.test(String(form.game)) || Number(form.game) < 1) {
    return "Select a game.";
  }
  if (!/^[1-7]$/.test(String(form.weekday))) {
    return "Select a valid weekday.";
  }
  if (!/^\d+$/.test(String(form.display_order)) || Number(form.display_order) < 1) {
    return "Display order must be 1 or greater.";
  }
  if (form.is_whole_day) {
    return "";
  }
  if (!form.closing_time || !form.draw_time) {
    return "Timed schedules require both Closing Time and Draw Time.";
  }
  if (form.draw_time <= form.closing_time) {
    return "Draw Time must be later than Closing Time.";
  }
  return "";
}

export function schedulePayload(form) {
  const isWholeDay = Boolean(form.is_whole_day);
  return {
    game: Number(form.game),
    weekday: Number(form.weekday),
    display_order: Number(form.display_order),
    is_whole_day: isWholeDay,
    closing_time: isWholeDay ? null : form.closing_time,
    draw_time: isWholeDay ? null : form.draw_time,
    is_active: Boolean(form.is_active),
  };
}
