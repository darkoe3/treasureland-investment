export const WEEKDAYS = [
  { value: 1, label: "Monday" },
  { value: 2, label: "Tuesday" },
  { value: 3, label: "Wednesday" },
  { value: 4, label: "Thursday" },
  { value: 5, label: "Friday" },
  { value: 6, label: "Saturday" },
  { value: 7, label: "Sunday" },
];

export function categoryLabel(category) {
  return { TIMED: "Timed", GHANA: "Ghana (Whole Day)", DOUBLE_CHANCE: "Double Chance" }[category] || "";
}

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

export function validateWeeklySchedule(entries = [], games = []) {
  const gameById = new Map(games.map((game) => [String(game.id), game]));
  return WEEKDAYS.map((weekday) => {
    const activeEntries = entries.filter((entry) => {
      const game = gameById.get(String(entry.game));
      return Number(entry.weekday) === weekday.value && entry.is_active !== false && Boolean(game) && game.is_active !== false;
    });
    const expectedCount = weekday.value === 7 ? 6 : 7;
    const categories = activeEntries.map((entry) => {
      const game = gameById.get(String(entry.game));
      const category = game?.category || entry.category;
      return category === "GHANA_GAME" ? "GHANA" : category;
    });
    const issues = [];

    if (activeEntries.length !== expectedCount) {
      issues.push(`Expected ${expectedCount} active games; found ${activeEntries.length}.`);
    }
    if (categories.filter((category) => category === "GHANA").length !== 1) {
      issues.push("Expected exactly one Ghana Game.");
    }
    if (categories.filter((category) => category === "DOUBLE_CHANCE").length !== 1) {
      issues.push("Expected exactly one Double Chance game.");
    }
    if (categories.filter((category) => category === "TIMED").length !== expectedCount - 2) {
      issues.push(`Expected ${expectedCount - 2} Timed games.`);
    }
    if (new Set(activeEntries.map((entry) => String(entry.game))).size !== activeEntries.length) {
      issues.push("Active game assignments must be unique for this weekday.");
    }
    if (new Set(activeEntries.map((entry) => String(entry.display_order))).size !== activeEntries.length) {
      issues.push("Active display order values must be unique for this weekday.");
    }

    return { ...weekday, expectedCount, activeCount: activeEntries.length, issues, ready: issues.length === 0 };
  });
}

export function emptyScheduleForm() {
  return {
    id: "",
    game: "",
    weekday: "",
    display_order: "1",
    category: "TIMED",
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
    category: entry.category,
    is_whole_day: Boolean(entry.is_whole_day),
    closing_time: entry.closing_time || "",
    draw_time: entry.draw_time || "",
    is_active: Boolean(entry.is_active),
  };
}

export function withScheduleMode(form, isWholeDay) {
  return {
    ...form,
    category: isWholeDay ? (form.category === "DOUBLE_CHANCE" ? "DOUBLE_CHANCE" : "GHANA") : "TIMED",
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
  const seconds = (value) => {
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?$/.test(value)) return NaN;
    const [hours, minutes, seconds = 0] = value.split(":").map(Number);
    return hours * 3600 + minutes * 60 + seconds;
  };
  const closing = seconds(form.closing_time);
  const draw = seconds(form.draw_time);
  if (!Number.isFinite(closing) || !Number.isFinite(draw)) {
    return "Enter valid Closing Time and Draw Time in Ghana local time (Africa/Accra).";
  }
  if (draw <= closing) {
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
    category: isWholeDay ? (form.category === "DOUBLE_CHANCE" ? "DOUBLE_CHANCE" : "GHANA") : "TIMED",
    is_whole_day: isWholeDay,
    closing_time: isWholeDay ? null : form.closing_time,
    draw_time: isWholeDay ? null : form.draw_time,
    is_active: Boolean(form.is_active),
  };
}
