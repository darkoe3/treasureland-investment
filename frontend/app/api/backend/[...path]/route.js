import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { validateCsrf } from "../../../../lib/csrf";
import { resolveBackendProxyRequest } from "../../../../lib/backend-proxy";
import { authenticatedBackendRequestWithStatus, ApiError } from "../../../../lib/server-api";

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
      backendRequest: authenticatedBackendRequestWithStatus,
    });
    maybeLogDiagnostics(result.diagnostics);
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
