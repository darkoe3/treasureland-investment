import PaymentsClient from "../../../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../../../lib/require-user";

export default async function PaymentPayerDetailPage({ params }) {
  const user = await requireDashboardUser("/dashboard/payments/payers");
  const { id } = await params;
  return <PaymentsClient user={user} view="payer" recordId={id} />;
}
