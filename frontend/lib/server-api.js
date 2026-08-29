import "server-only";

import { cookies } from "next/headers";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearAuthCookies, setAuthCookies } from "./auth-cookies";
import { ApiError, backendRequestWithFetch, backendRequestWithFetchResponse } from "./backend-request";

export { apiBaseUrl, buildBackendUrl } from "./backend-url";
export { ApiError } from "./backend-request";

export async function backendRequest(path, options = {}) {
  return backendRequestWithFetch(path, options);
}

export async function backendRequestWithStatus(path, options = {}) {
  return backendRequestWithFetchResponse(path, options);
}

export async function refreshTokens(cookieStore = null) {
  const store = cookieStore || (await cookies());
  const refresh = store.get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    throw new ApiError("Missing refresh token.", 401);
  }
  try {
    const payload = await backendRequest("/auth/refresh/", {
      method: "POST",
      body: JSON.stringify({ refresh }),
    });
    setAuthCookies(store, { access: payload.access, refresh: payload.refresh || refresh });
    return payload.access;
  } catch (error) {
    clearAuthCookies(store);
    throw error;
  }
}

export async function authenticatedBackendRequest(path, options = {}, allowRefresh = false) {
  const store = await cookies();
  const access = store.get(ACCESS_COOKIE)?.value;
  if (!access) {
    throw new ApiError("Missing access token.", 401);
  }
  try {
    return await backendRequest(path, {
      ...options,
      headers: {
        ...(options.headers || {}),
        Authorization: `Bearer ${access}`,
      },
    });
  } catch (error) {
    if (allowRefresh && error.status === 401) {
      const freshAccess = await refreshTokens(store);
      return backendRequest(path, {
        ...options,
        headers: {
          ...(options.headers || {}),
          Authorization: `Bearer ${freshAccess}`,
        },
      });
    }
    throw error;
  }
}

export async function authenticatedBackendRequestWithStatus(path, options = {}, allowRefresh = false) {
  const store = await cookies();
  const access = store.get(ACCESS_COOKIE)?.value;
  if (!access) {
    throw new ApiError("Missing access token.", 401);
  }
  try {
    return await backendRequestWithStatus(path, {
      ...options,
      headers: {
        ...(options.headers || {}),
        Authorization: `Bearer ${access}`,
      },
    });
  } catch (error) {
    if (allowRefresh && error.status === 401) {
      const freshAccess = await refreshTokens(store);
      return backendRequestWithStatus(path, {
        ...options,
        headers: {
          ...(options.headers || {}),
          Authorization: `Bearer ${freshAccess}`,
        },
      });
    }
    throw error;
  }
}

export async function getCurrentUser(allowRefresh = false) {
  return authenticatedBackendRequest("/auth/me/", {}, allowRefresh);
}

export async function safeCurrentUser() {
  try {
    return await getCurrentUser(false);
  } catch {
    return null;
  }
}
