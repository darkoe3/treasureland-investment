export function paymentList(payload) {
  if (Array.isArray(payload)) return payload;
  return Array.isArray(payload?.results) ? payload.results : [];
}

export function paymentMoney(value) {
  const amount = Number(value || 0);
  return Number.isFinite(amount) ? amount : 0;
}

export function formatGhanaMoney(value) {
  return `GH₵ ${paymentMoney(value).toLocaleString("en-GH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function paymentStatusLabel(status) {
  return String(status || "UNKNOWN").replaceAll("_", " ");
}

export function createPaymentIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  throw new Error("A secure browser random source is required for payment attempts.");
}

export function paymentFingerprint(form) {
  return JSON.stringify({
    obligation: form.obligation,
    amount_received: form.amount_received,
    payment_method: form.payment_method,
    payment_reference: form.payment_reference,
    notes: form.notes,
    payment_date: form.payment_date,
  });
}

export function analyticsQuery(filters = {}) {
  const params = new URLSearchParams();
  for (const agency of filters.agencies || []) params.append("agency", agency);
  for (const [key, value] of Object.entries(filters)) {
    if (key !== "agencies" && value) params.set(key, value);
  }
  return params.toString();
}
