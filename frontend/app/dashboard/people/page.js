import { requireDashboardUser } from "../../../lib/require-user";
import { authenticatedBackendRequest } from "../../../lib/server-api";
import PeopleTpmClient from "../../../components/PeopleTpmClient";

export const dynamic = "force-dynamic";

export default async function PeoplePage() {
  const user = await requireDashboardUser("/dashboard/people");
  const agenciesPayload = await authenticatedBackendRequest("/agencies/").catch(() => []);
  const agencies = agenciesPayload.results || agenciesPayload;
  return <PeopleTpmClient user={user} initialAgencies={agencies} />;
}
