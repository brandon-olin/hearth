/**
 * Dedicated proxy for POST /api/documents/bulk-import.
 * Specific routes always win over the [...path] catch-all in Next.js App Router.
 */

import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const targetUrl = `${API_URL}/documents/bulk-import`;

  const headers: Record<string, string> = {
    "content-type": req.headers.get("content-type") ?? "application/json",
  };

  const auth = req.headers.get("authorization");
  if (auth) headers["authorization"] = auth;

  const cookie = req.headers.get("cookie");
  if (cookie) headers["cookie"] = cookie;

  const upstream = await fetch(targetUrl, {
    method: "POST",
    headers,
    body: await req.text(),
  });

  const responseHeaders = new Headers();
  const ct = upstream.headers.get("content-type");
  if (ct) responseHeaders.set("content-type", ct);

  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") responseHeaders.append("set-cookie", value);
  });

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}
