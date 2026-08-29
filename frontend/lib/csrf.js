export const CSRF_COOKIE = "tl_csrf";
export const CSRF_HEADER = "x-csrf-token";

export function csrfCookieOptions() {
  return {
    httpOnly: false,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60,
  };
}

export function createCsrfToken() {
  return crypto.randomUUID();
}

export function validateCsrf(request, cookieStore) {
  const cookieToken = cookieStore.get(CSRF_COOKIE)?.value;
  const headerToken = request.headers.get(CSRF_HEADER);
  return Boolean(cookieToken && headerToken && cookieToken === headerToken);
}
