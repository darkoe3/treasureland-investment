import AccessDenied from "../../../components/AccessDenied";
import ReportsClient from "../../../components/ReportsClient";
import { authenticatedBackendRequest, safeCurrentUser } from "../../../lib/server-api";

export default async function ReportsPage() {
  const user = await safeCurrentUser();
  if (!user || user.role !== "SUPER_ADMIN") {
    return <AccessDenied />;
  }
  const payload = await authenticatedBackendRequest("/agencies/");
  return <ReportsClient agencies={payload.results || payload} />;
}
