import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { validateCsrf } from "../../../../lib/csrf";
import { resolveBackendProxyRequest } from "../../../../lib/backend-proxy";
import { isBinaryBackendProxyPath } from "../../../../lib/controlled-proxy-path";
import { authenticatedBackendRequestWithStatus, authenticatedBackendRawResponse, ApiError } from "../../../../lib/server-api";

function maybeLogDiagnostics(diagnostics) {
  if (process.env.TL_PROXY_DEBUG !== "1") {
    return;
  }
  console.info("backend proxy resolution", diagnostics);
}

async function proxyRequest(request, context) {
  try {
    const store = await cookies();
    const result = await resolveBackendProxyRequest(request, context, {
      cookieStore: store,
      validateCsrf,
      backendRequest: async (backendPath, options = {}) => {
        if (options.binary) {
          const response = await authenticatedBackendRawResponse(backendPath, { method: options.method, accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/json" });
          return {
            status: response.status,
            body: response.body,
            contentType: response.headers.get("content-type"),
            contentDisposition: response.headers.get("content-disposition"),
          };
        }
        return authenticatedBackendRequestWithStatus(backendPath, options);
      },
    });
    maybeLogDiagnostics(result.diagnostics);
    if (isBinaryBackendProxyPath(result.diagnostics.normalizedPath, request.method)) {
      const headers = new Headers();
      headers.set("Content-Type", result.contentType || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
      if (result.status < 400) {
        headers.set("Content-Disposition", result.contentDisposition || 'attachment; filename="treasureland-report.xlsx"');
      }
      return new Response(result.body, { status: result.status, headers });
    }
    return NextResponse.json(result.payload ?? {}, { status: result.status });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    const payload =
      error instanceof ApiError && error.exposePayload && error.payload
        ? error.payload
        : { detail: status >= 500 ? "Upstream service error." : "Request failed." };
    return NextResponse.json(payload, { status });
  }
}

export async function GET(request, context) {
  return proxyRequest(request, context);
}

export async function POST(request, context) {
  return proxyRequest(request, context);
}

export async function PATCH(request, context) {
  return proxyRequest(request, context);
}

export async function DELETE(request, context) {
  return proxyRequest(request, context);
}
