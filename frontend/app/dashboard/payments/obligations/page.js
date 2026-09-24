import PaymentsClient from "../../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../../lib/require-user";

export default async function PaymentObligationsPage() {
  const user = await requireDashboardUser("/dashboard/payments/obligations");
  return <PaymentsClient user={user} view="obligations" />;
}
