import PaymentsClient from "../../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../../lib/require-user";

export default async function PaymentAnalyticsPage() {
  const user = await requireDashboardUser("/dashboard/payments/analytics");
  return <PaymentsClient user={user} view="analytics" />;
}
