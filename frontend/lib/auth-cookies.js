export const ACCESS_COOKIE = "tl_access";
export const REFRESH_COOKIE = "tl_refresh";

export const ACCESS_MAX_AGE_SECONDS = 9 * 60;
export const REFRESH_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

export function cookieOptions(maxAge) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
  };
}

export function setAuthCookies(cookieStore, tokens) {
  if (tokens.access) {
    cookieStore.set(ACCESS_COOKIE, tokens.access, cookieOptions(ACCESS_MAX_AGE_SECONDS));
  }
  if (tokens.refresh) {
    cookieStore.set(REFRESH_COOKIE, tokens.refresh, cookieOptions(REFRESH_MAX_AGE_SECONDS));
  }
}

export function clearAuthCookies(cookieStore) {
  cookieStore.set(ACCESS_COOKIE, "", cookieOptions(0));
  cookieStore.set(REFRESH_COOKIE, "", cookieOptions(0));
}
