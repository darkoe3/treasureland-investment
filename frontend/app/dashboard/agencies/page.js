import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function AgenciesPage() {
  await requireDashboardUser("/dashboard/agencies");
  return <PlaceholderPage title="Agencies" description="Agency records are loaded through the secured backend. Full agency editing screens are reserved for a later phase." />;
}
