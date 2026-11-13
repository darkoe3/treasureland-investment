import ProfileClient from "../../../components/ProfileClient";
import { requireDashboardUser } from "../../../lib/require-user";
export default async function ProfilePage() {
  await requireDashboardUser("/dashboard/profile");
  return <ProfileClient />;
}
