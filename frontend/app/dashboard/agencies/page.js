import AgenciesClient from "../../../components/AgenciesClient";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function AgenciesPage() {
  const user = await requireDashboardUser("/dashboard/agencies");
  return <AgenciesClient user={user} />;
}
