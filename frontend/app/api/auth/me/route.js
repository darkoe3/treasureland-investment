import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { clearAuthCookies } from "../../../../lib/auth-cookies";
import { ApiError, getCurrentUser } from "../../../../lib/server-api";

export async function GET() {
  const store = await cookies();
  try {
    const user = await getCurrentUser(true);
    return NextResponse.json({ user });
  } catch (error) {
    clearAuthCookies(store);
    const status = error instanceof ApiError ? error.status : 401;
    return NextResponse.json({ detail: "Not authenticated." }, { status });
  }
}
