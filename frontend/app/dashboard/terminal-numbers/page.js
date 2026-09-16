import { requireDashboardUser } from "../../../lib/require-user";
import { authenticatedBackendRequest } from "../../../lib/server-api";
import TerminalNumbersClient from "../../../components/TerminalNumbersClient";

export const dynamic = "force-dynamic";
export default async function TerminalNumbersPage() {
  const user = await requireDashboardUser("/dashboard/terminal-numbers");
  const payload = await authenticatedBackendRequest("/agencies/");
  return <TerminalNumbersClient user={user} agencies={payload.results || payload} />;
}
