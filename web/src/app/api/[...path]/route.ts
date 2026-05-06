/**
 * Catch-all API proxy — forwards all /api/* requests to the FastAPI backend.
 * Parses the path directly from the URL to avoid depending on the params API.
 */

import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function proxy(request: NextRequest): Promise<NextResponse> {
  // Strip the leading /api prefix to get the backend path.
  const backendPath = request.nextUrl.pathname.replace(/^\/api/, "");
  const search = request.nextUrl.search;
  const targetUrl = `${API_URL}${backendPath}${search}`;

  const headers: Record<string, string> = {
    "content-type": request.headers.get("content-type") ?? "application/json",
  };

  const auth = request.headers.get("authorization");
  if (auth) headers["authorization"] = auth;

  const cookie = request.headers.get("cookie");
  if (cookie) headers["cookie"] = cookie;

  const init: RequestInit = { method: request.method, headers };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = await request.text();
  }

  const upstream = await fetch(targetUrl, init);
  const responseHeaders = new Headers();

  const ct = upstream.headers.get("content-type");
  if (ct) responseHeaders.set("content-type", ct);

  // Forward Set-Cookie so httpOnly refresh cookies propagate correctly.
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") responseHeaders.append("set-cookie", value);
  });

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export async function GET(req: NextRequest)    { return proxy(req); }
export async function POST(req: NextRequest)   { return proxy(req); }
export async function PATCH(req: NextRequest)  { return proxy(req); }
export async function DELETE(req: NextRequest) { return proxy(req); }
export async function PUT(req: NextRequest)    { return proxy(req); }
