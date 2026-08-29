import PlaceholderPage from "../../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../../lib/require-user";

export default async function NewDailySheetPage() {
  await requireDashboardUser("/dashboard/daily-sheets/new");
  return <PlaceholderPage title="New Daily Sheet" description="Daily transaction entry starts in a later phase. This placeholder confirms route protection and role navigation only." />;
}
