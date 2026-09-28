const currencyFormatter = new Intl.NumberFormat("en-NG", {
  style: "currency",
  currency: "NGN",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatCurrency(value) {
  const parsed = Number(value || 0);
  const amount = Number.isFinite(parsed) ? parsed : 0;
  return currencyFormatter.format(amount)
    .replace(/^NGN[\s\u00a0\u202f]*/u, "₦")
    .replace(/^₦[\s\u00a0\u202f]+/u, "₦");
}