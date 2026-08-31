export const REPORT_STATUSES = ["APPROVED", "DRAFT", "SUBMITTED", "RETURNED", "REOPENED"];

export function todayISO(now = new Date()) {
  return now.toISOString().slice(0, 10);
}

export function monthFromDate(value = todayISO()) {
  return value.slice(5, 7);
}

export function yearFromDate(value = todayISO()) {
  return value.slice(0, 4);
}

export function resolvePeriodDisplay(filters) {
  if (filters.period === "daily") {
    return { start: filters.date, end: filters.date };
  }
  if (filters.period === "weekly") {
    const selected = new Date(`${filters.date}T00:00:00Z`);
    if (Number.isNaN(selected.getTime())) return { start: "", end: "" };
    const day = selected.getUTCDay() || 7;
    const monday = new Date(selected);
    monday.setUTCDate(selected.getUTCDate() - day + 1);
    const sunday = new Date(monday);
    sunday.setUTCDate(monday.getUTCDate() + 6);
    return { start: monday.toISOString().slice(0, 10), end: sunday.toISOString().slice(0, 10) };
  }
  if (filters.period === "monthly") {
    const year = Number(filters.year);
    const month = Number(filters.month);
    if (!year || !month) return { start: "", end: "" };
    const end = new Date(Date.UTC(year, month, 0));
    return { start: `${filters.year}-${String(month).padStart(2, "0")}-01`, end: end.toISOString().slice(0, 10) };
  }
  return { start: filters.startDate, end: filters.endDate };
}

export function validateReportFilters(filters) {
  if (!filters.agency) return "Select an agency.";
  if (!filters.statuses?.length) return "Select at least one status.";
  if (filters.period === "daily" || filters.period === "weekly") {
    if (!filters.date) return "Select a report date.";
  }
  if (filters.period === "monthly") {
    if (!filters.month || !filters.year) return "Select a month and year.";
  }
  if (filters.period === "custom") {
    if (!filters.startDate || !filters.endDate) return "Select both custom start and end dates.";
    if (filters.startDate > filters.endDate) return "Custom start date must be on or before end date.";
  }
  return "";
}

export function buildReportQuery(filters) {
  const error = validateReportFilters(filters);
  if (error) {
    throw new Error(error);
  }
  const params = new URLSearchParams();
  params.set("agency", filters.agency);
  params.set("period", filters.period);
  if (filters.period === "daily" || filters.period === "weekly") {
    params.set("date", filters.date);
  } else if (filters.period === "monthly") {
    params.set("month", String(Number(filters.month)));
    params.set("year", filters.year);
  } else {
    params.set("start_date", filters.startDate);
    params.set("end_date", filters.endDate);
  }
  filters.statuses.forEach((status) => params.append("status", status));
  return params.toString();
}

export function moneyText(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number);
}

export function differenceClass(value) {
  const number = Number(value || 0);
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "zero";
}

export function filenameFromDisposition(disposition, fallback = "treasureland-report.xlsx") {
  const match = /filename="?([^"]+)"?/i.exec(disposition || "");
  return match?.[1] || fallback;
}
