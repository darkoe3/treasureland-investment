import AccessDenied from "../../../../components/AccessDenied";
import AccountantForm from "../../../../components/AccountantForm";
import { authenticatedBackendRequest, safeCurrentUser } from "../../../../lib/server-api";
import { activeAgenciesFromPayload } from "../../../../lib/resource-shapes";

export const dynamic = "force-dynamic";

export default async function AccountantDetailPage({ params }) {
  const user = await safeCurrentUser();
  if (!user || user.role !== "SUPER_ADMIN") {
    return <AccessDenied />;
  }
  const { id } = await params;
  const accountant = await authenticatedBackendRequest(`/accountants/${id}/`);
  let agencies = [];
  let agencyLoadError = "";
  try {
    const agenciesPayload = await authenticatedBackendRequest("/agencies/");
    agencies = activeAgenciesFromPayload(agenciesPayload);
  } catch {
    agencyLoadError = "Unable to load active agencies. Profile changes are still available, but agency permissions will not be changed.";
  }
  return <AccountantForm accountant={accountant} agencies={agencies} agencyLoadError={agencyLoadError} />;
}
