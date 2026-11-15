import SettingsClient from "../../../components/SettingsClient";
import AccessDenied from "../../../components/AccessDenied";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function SettingsPage() {
  const user = await requireDashboardUser("/dashboard/settings");
  if (user.role !== "SUPER_ADMIN") return <AccessDenied />;
  return <SettingsClient />;
}
