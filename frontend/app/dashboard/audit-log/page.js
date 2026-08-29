import PlaceholderPage from "../../../components/PlaceholderPage";
import { requireDashboardUser } from "../../../lib/require-user";

export default async function AuditLogPage() {
  await requireDashboardUser("/dashboard/audit-log");
  return <PlaceholderPage title="Audit Log" description="Audit history is protected by backend permissions. Complete audit browsing screens are outside Phase 3." />;
}
