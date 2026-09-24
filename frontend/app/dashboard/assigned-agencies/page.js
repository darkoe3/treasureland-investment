import AgenciesClient from "../../../components/AgenciesClient";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function AssignedAgenciesPage() {
  const user = await requireDashboardUser("/dashboard/assigned-agencies");
  return <AgenciesClient user={user} />;
}
