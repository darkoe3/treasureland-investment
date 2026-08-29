import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function SettingsPage() {
  await requireDashboardUser("/dashboard/settings");
  return <PlaceholderPage title="Settings" description="Application settings will be expanded later. This protected route is present for the Phase 3 Super Admin layout." />;
}
