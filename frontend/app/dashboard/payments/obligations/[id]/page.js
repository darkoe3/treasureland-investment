import PaymentsClient from "../../../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../../../lib/require-user";

export default async function PaymentObligationDetailPage({ params }) {
  const user = await requireDashboardUser("/dashboard/payments/obligations");
  const { id } = await params;
  return <PaymentsClient user={user} view="obligation" recordId={id} />;
}
