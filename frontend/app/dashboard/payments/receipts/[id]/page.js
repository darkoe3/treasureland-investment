import PaymentsClient from "../../../../../components/PaymentsClient";
import { requireDashboardUser } from "../../../../../lib/require-user";

export default async function PaymentReceiptPage({ params }) {
  const user = await requireDashboardUser("/dashboard/payments");
  const { id } = await params;
  return <PaymentsClient user={user} view="receipt" recordId={id} />;
}
