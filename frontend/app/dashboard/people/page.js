import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function PeoplePage() {
  await requireDashboardUser("/dashboard/people");
  return <PlaceholderPage title="People & TPM Codes" description="People and TPM code administration remains available through the secured API. Full frontend management screens are outside Phase 3." />;
}
