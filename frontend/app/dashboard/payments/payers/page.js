import PaymentsClient from "../../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../../lib/require-user";

export default async function PaymentPayersPage() {
  const user = await requireDashboardUser("/dashboard/payments/payers");
  return <PaymentsClient user={user} view="payers" />;
}
