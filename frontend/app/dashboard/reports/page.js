import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function ReportsPage() {
  await requireDashboardUser("/dashboard/reports");
  return <PlaceholderPage title="Reports" description="Reporting navigation is permission-aware, but complete reporting screens and Excel export are intentionally out of scope for Phase 3." />;
}
