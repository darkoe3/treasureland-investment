import PaymentsClient from "../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function PaymentsPage() {
  const user = await requireDashboardUser("/dashboard/payments");
  return <PaymentsClient user={user} view="overview" />;
}
