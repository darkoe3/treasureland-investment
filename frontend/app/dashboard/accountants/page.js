import AccessDenied from "../../../components/AccessDenied";
import AccountantsClient from "../../../components/AccountantsClient";
import { authenticatedBackendRequest, safeCurrentUser } from "../../../lib/server-api";

export const dynamic = "force-dynamic";

export default async function AccountantsPage() {
  const user = await safeCurrentUser();
  if (!user || user.role !== "SUPER_ADMIN") {
    return <AccessDenied />;
  }
  const payload = await authenticatedBackendRequest("/accountants/");
  const accountants = payload.results || payload;
  return <AccountantsClient initialAccountants={accountants} />;
}
