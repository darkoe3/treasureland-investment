import { NextResponse } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearAuthCookies, setAuthCookies } from "./lib/auth-cookies";
import { buildBackendUrl } from "./lib/backend-url";

const TIMEOUT_MS = 8000;

function safeNext(pathname, search) {
  const target = `${pathname}${search || ""}`;
  if (!target.startsWith("/dashboard") || target.startsWith("//")) {
    return "/dashboard";
  }
  return target;
}

async function timedFetch(url, options) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
  } finally {
    clearTimeout(timeout);
  }
}

async function validateAccess(access) {
  if (!access) {
    return false;
  }
  try {
    const response = await timedFetch(buildBackendUrl("/auth/me/"), {
      headers: { Authorization: `Bearer ${access}` },
    });
    return response.ok;
  } catch {
    return false;
  }
}

async function refreshAccess(refresh) {
  if (!refresh) {
    return null;
  }
  try {
    const response = await timedFetch(buildBackendUrl("/auth/refresh/"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!response.ok) {
      return null;
    }
    return response.json();
  } catch {
    return null;
  }
}

async function authenticationResult(request) {
  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  if (await validateAccess(access)) {
    return { authenticated: true, tokens: null };
  }
  const tokens = await refreshAccess(refresh);
  if (tokens?.access && (await validateAccess(tokens.access))) {
    return { authenticated: true, tokens: { access: tokens.access, refresh: tokens.refresh || refresh } };
  }
  return { authenticated: false, tokens: null };
}

export async function proxy(request) {
  const { pathname, search } = request.nextUrl;
  const result = await authenticationResult(request);

  if (pathname.startsWith("/dashboard") && !result.authenticated) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.search = "";
    loginUrl.searchParams.set("next", safeNext(pathname, search));
    const response = NextResponse.redirect(loginUrl);
    clearAuthCookies(response.cookies);
    return response;
  }

  if (pathname === "/login" && result.authenticated) {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = "/dashboard";
    dashboardUrl.search = "";
    const response = NextResponse.redirect(dashboardUrl);
    if (result.tokens) {
      setAuthCookies(response.cookies, result.tokens);
    }
    return response;
  }

  const response = NextResponse.next();
  if (result.tokens) {
    setAuthCookies(response.cookies, result.tokens);
  }
  return response;
}

export const config = {
  matcher: ["/dashboard/:path*", "/login"],
};
