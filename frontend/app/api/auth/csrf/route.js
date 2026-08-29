import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { CSRF_COOKIE, createCsrfToken, csrfCookieOptions } from "../../../../lib/csrf";

export async function GET() {
  const token = createCsrfToken();
  const store = await cookies();
  store.set(CSRF_COOKIE, token, csrfCookieOptions());
  return NextResponse.json({ csrfToken: token });
}
