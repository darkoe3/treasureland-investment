import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function HistoryPage() {
  await requireDashboardUser("/dashboard/history");
  return <PlaceholderPage title="History" description="History navigation appears only for accountants with view-history permission. Complete audit browsing is outside Phase 3." />;
}
