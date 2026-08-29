import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function GameSchedulePage() {
  await requireDashboardUser("/dashboard/game-schedule");
  return <PlaceholderPage title="Game Schedule" description="Scheduled game data is used by the overview. A complete schedule editor is not part of Phase 3." />;
}
