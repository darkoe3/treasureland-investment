import { cookies } from "next/headers";
import { validateCsrf } from "../../../../lib/csrf";
import { controlledBackendProxyResponse } from "../../../../lib/backend-proxy";
import { authenticatedBackendRequestWithStatus, authenticatedBackendRawResponse } from "../../../../lib/server-api";

export const maxDuration = 60;

async function proxyRequest(request, context) {
  return controlledBackendProxyResponse(request, context, {
    cookieStore: await cookies(),
    validateCsrf,
    backendRequest: async (backendPath, options = {}) => {
      if (options.binary) {
        const response = await authenticatedBackendRawResponse(backendPath, { method: options.method, accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/json" });
        return {
          status: response.status, body: response.body,
          contentType: response.headers.get("content-type"),
          contentDisposition: response.headers.get("content-disposition"),
        };
      }
      // The browser owns the single refresh/retry; never retry a proxy submission here.
      const requestOptions = backendPath === "/daily-sheet-imports/preview"
        ? { ...options, timeoutMs: 60000 }
        : options;
      return authenticatedBackendRequestWithStatus(backendPath, requestOptions, false);
    },
  });
}

export async function GET(request, context) { return proxyRequest(request, context); }
export async function POST(request, context) { return proxyRequest(request, context); }
export async function PATCH(request, context) { return proxyRequest(request, context); }
export async function DELETE(request, context) { return proxyRequest(request, context); }
