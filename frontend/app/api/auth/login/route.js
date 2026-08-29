import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { setAuthCookies } from "../../../../lib/auth-cookies";
import { validateCsrf } from "../../../../lib/csrf";
import { ApiError, backendRequest } from "../../../../lib/server-api";

export async function POST(request) {
  const store = await cookies();
  if (!validateCsrf(request, store)) {
    return NextResponse.json({ detail: "Invalid security token." }, { status: 403 });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON request." }, { status: 400 });
  }

  const email = String(body.email || "").trim();
  const password = String(body.password || "");
  if (!email || !password) {
    return NextResponse.json({ detail: "Email and password are required." }, { status: 400 });
  }

  try {
    const payload = await backendRequest("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAuthCookies(store, { access: payload.access, refresh: payload.refresh });
    return NextResponse.json({ user: payload.user });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    const detail = status === 401 || status === 400 ? "Invalid email or password." : "Unable to sign in right now.";
    return NextResponse.json({ detail }, { status });
  }
}
