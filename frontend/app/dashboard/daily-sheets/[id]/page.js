import DailySheetDetailClient from "../../../../components/DailySheetDetailClient";
import { requireDashboardUser } from "../../../../lib/require-user";
import { authenticatedBackendRequest } from "../../../../lib/server-api";

export const dynamic = "force-dynamic";

export default async function DailySheetDetailPage({ params }) {
  const user = await requireDashboardUser("/dashboard/daily-sheets");
  const { id } = await params;
  const sheet = await authenticatedBackendRequest(`/daily-sheets/${id}/summary/`);
  const peoplePayload = await authenticatedBackendRequest(`/people/?agency=${sheet.agency}`).catch(() => []);
  return <DailySheetDetailClient user={user} initialSheet={sheet} initialPeople={peoplePayload.results || peoplePayload} />;
}
