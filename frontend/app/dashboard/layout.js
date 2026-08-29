import { redirect } from "next/navigation";
import DashboardShell from "../../components/DashboardShell";
import { safeCurrentUser } from "../../lib/server-api";

export const metadata = {
  title: "Dashboard | Treasureland Investment Limited",
};

export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }) {
  const user = await safeCurrentUser();
  if (!user) {
    redirect("/login?next=/dashboard");
  }

  return <DashboardShell user={user}>{children}</DashboardShell>;
}
