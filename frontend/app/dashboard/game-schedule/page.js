import GameScheduleClient from "../../../components/GameScheduleClient";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function GameSchedulePage() {
  const user = await requireDashboardUser("/dashboard/game-schedule");
  return <GameScheduleClient user={user} />;
}
