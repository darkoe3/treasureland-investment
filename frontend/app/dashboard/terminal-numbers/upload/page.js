import { redirect } from "next/navigation";
import { requireDashboardUser } from "../../../../lib/require-user";
import { authenticatedBackendRequest } from "../../../../lib/server-api";
import TerminalNumbersClient from "../../../../components/TerminalNumbersClient";

export const dynamic = "force-dynamic";
export default async function TerminalUploadPage() {
  const user = await requireDashboardUser("/dashboard/terminal-numbers/upload");
  if (user.role !== "SUPER_ADMIN") redirect("/dashboard/terminal-numbers");
  const payload = await authenticatedBackendRequest("/agencies/");
  return <TerminalNumbersClient user={user} agencies={payload.results || payload} uploadPage />;
}
