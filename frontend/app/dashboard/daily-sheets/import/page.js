import DailySheetImportClient from "../../../../components/DailySheetImportClient";
import { requireDashboardUser } from "../../../../lib/require-user";
import { authenticatedBackendRequest } from "../../../../lib/server-api";
import { activeAgenciesFromPayload } from "../../../../lib/resource-shapes";

export default async function DailySheetImportPage() {
  const user = await requireDashboardUser("/dashboard/daily-sheets/import");
  const agenciesPayload = await authenticatedBackendRequest("/agencies/").catch(() => []);
  return <DailySheetImportClient user={user} agencies={activeAgenciesFromPayload(agenciesPayload)} />;
}
