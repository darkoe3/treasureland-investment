import DailySheetsClient from "../../../components/DailySheetsClient";
import { requireDashboardUser } from "../../../lib/require-user";
import { authenticatedBackendRequest } from "../../../lib/server-api";

export const dynamic = "force-dynamic";

export default async function DailySheetsPage() {
  const user = await requireDashboardUser("/dashboard/daily-sheets");
  const agenciesPayload = await authenticatedBackendRequest("/agencies/").catch(() => []);
  return <DailySheetsClient user={user} initialAgencies={agenciesPayload.results || agenciesPayload} />;
}
