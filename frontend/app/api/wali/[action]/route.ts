import { NextRequest, NextResponse } from "next/server";

import { isLocalRequest } from "@/lib/local-request";

const GET_ACTIONS = new Set(["info", "pending"]);
const POST_ACTIONS = new Set(["chat", "confirm", "cancel", "mandate", "reset"]);
const BACKEND = process.env.WALI_API_ORIGIN ?? "http://127.0.0.1:8000";

type Context = { params: Promise<{ action: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { action } = await context.params;
  if (!GET_ACTIONS.has(action))
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  if (!isLocalRequest(request.headers.get("host"), request.headers.get("origin"))) {
    return NextResponse.json({ detail: "Refused." }, { status: 403 });
  }
  const upstream = new URL(`/api/${action}`, BACKEND);
  if (action === "pending") {
    const role = request.nextUrl.searchParams.get("role");
    if (role) upstream.searchParams.set("role", role);
  }
  return forward(upstream);
}

export async function POST(request: NextRequest, context: Context) {
  const { action } = await context.params;
  if (!POST_ACTIONS.has(action))
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  if (!isLocalRequest(request.headers.get("host"), request.headers.get("origin"))) {
    return NextResponse.json({ detail: "Refused." }, { status: 403 });
  }
  if (
    request.headers.get("content-type")?.split(";")[0].trim() !==
    "application/json"
  ) {
    return NextResponse.json({ detail: "Refused." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON." }, { status: 400 });
  }
  return forward(new URL(`/api/${action}`, BACKEND), JSON.stringify(body));
}

async function forward(url: URL, body?: string) {
  try {
    // The browser Origin is intentionally not passed to FastAPI; the proxy sends only JSON.
    const response = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    const data = await response.text();
    return new NextResponse(data, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "The Wali API is unavailable. Start FastAPI on the configured local origin.",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
