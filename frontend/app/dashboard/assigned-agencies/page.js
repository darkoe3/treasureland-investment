import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function AssignedAgenciesPage() {
  await requireDashboardUser("/dashboard/assigned-agencies");
  return <PlaceholderPage title="Assigned Agencies" description="Accountants can review their assigned agency access from the overview. A deeper agency workspace is planned for a later phase." />;
}
