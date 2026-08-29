import "server-only";

import { redirect } from "next/navigation";
import { safeCurrentUser } from "./server-api";

export async function requireDashboardUser(path = "/dashboard") {
  const user = await safeCurrentUser();
  if (!user) {
    redirect(`/login?next=${encodeURIComponent(path)}`);
  }
  return user;
}
