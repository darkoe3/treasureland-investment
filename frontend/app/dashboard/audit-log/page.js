import AuditLogClient from "../../../components/AuditLogClient";
import AccessDenied from "../../../components/AccessDenied";
import { requireDashboardUser } from "../../../lib/require-user";
export default async function AuditLogPage() {
  const user = await requireDashboardUser("/dashboard/audit-log");
  if (user.role !== "SUPER_ADMIN") return <AccessDenied />;
  return <AuditLogClient />;
}
