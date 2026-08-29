import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { clearAuthCookies, REFRESH_COOKIE } from "../../../../lib/auth-cookies";
import { validateCsrf } from "../../../../lib/csrf";
import { ApiError, refreshTokens } from "../../../../lib/server-api";

export async function POST(request) {
  const store = await cookies();
  if (!validateCsrf(request, store)) {
    return NextResponse.json({ detail: "Invalid security token." }, { status: 403 });
  }
  if (!store.get(REFRESH_COOKIE)?.value) {
    clearAuthCookies(store);
    return NextResponse.json({ detail: "Session expired." }, { status: 401 });
  }
  try {
    await refreshTokens(store);
    return NextResponse.json({ detail: "Session refreshed." });
  } catch (error) {
    clearAuthCookies(store);
    const status = error instanceof ApiError ? error.status : 401;
    return NextResponse.json({ detail: "Session expired." }, { status });
  }
}
