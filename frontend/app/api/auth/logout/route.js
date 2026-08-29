import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearAuthCookies } from "../../../../lib/auth-cookies";
import { validateCsrf } from "../../../../lib/csrf";
import { backendRequest } from "../../../../lib/server-api";

export async function POST(request) {
  const store = await cookies();
  if (!validateCsrf(request, store)) {
    return NextResponse.json({ detail: "Invalid security token." }, { status: 403 });
  }
  const access = store.get(ACCESS_COOKIE)?.value;
  const refresh = store.get(REFRESH_COOKIE)?.value;

  if (access && refresh) {
    try {
      await backendRequest("/auth/logout/", {
        method: "POST",
        headers: { Authorization: `Bearer ${access}` },
        body: JSON.stringify({ refresh }),
      });
    } catch {
      // Cookies are cleared even if backend token blacklisting is unavailable.
    }
  }

  clearAuthCookies(store);
  return NextResponse.json({ detail: "Signed out." });
}
