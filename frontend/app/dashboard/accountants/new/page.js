import AccessDenied from "../../../../components/AccessDenied";
import AccountantForm from "../../../../components/AccountantForm";
import { authenticatedBackendRequest, safeCurrentUser } from "../../../../lib/server-api";
import { activeAgenciesFromPayload } from "../../../../lib/resource-shapes";

export const dynamic = "force-dynamic";

export default async function NewAccountantPage() {
  const user = await safeCurrentUser();
  if (!user || user.role !== "SUPER_ADMIN") {
    return <AccessDenied />;
  }
  let agencies = [];
  let agencyLoadError = "";
  try {
    const payload = await authenticatedBackendRequest("/agencies/");
    agencies = activeAgenciesFromPayload(payload);
  } catch {
    agencyLoadError = "Unable to load active agencies. Accountant creation is paused until agencies can be loaded.";
  }
  return <AccountantForm agencies={agencies} agencyLoadError={agencyLoadError} />;
}
