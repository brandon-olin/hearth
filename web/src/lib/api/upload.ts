/**
 * Image upload utility for the BlockNote editor.
 *
 * BlockNote's `uploadFile` option expects a function that takes a File and
 * returns a Promise<string> — the URL to embed in the image block.
 *
 * The returned URL is stored in the block JSON in the database, so it must
 * be a stable, browser-accessible path.
 *
 * Web builds:    "/api/uploads/{uuid}.ext"  (served via the Next.js proxy)
 * Tauri builds:  "http://localhost:1338/uploads/{uuid}.ext" (direct to sidecar)
 */

import { getAccessToken } from "@/lib/auth/token";

const isTauri = process.env.NEXT_PUBLIC_TAURI === "true";
const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

/**
 * Upload an image to the server and return its browser-accessible URL.
 * Throws on network error or non-2xx response.
 */
export async function uploadImageFile(file: File): Promise<string> {
  const formData = new FormData();
  formData.append("file", file);

  const token = getAccessToken();
  const headers: HeadersInit = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}/uploads`, {
    method: "POST",
    credentials: isTauri ? "include" : "same-origin",
    headers,
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`Image upload failed (${res.status}): ${text}`);
  }

  const data = (await res.json()) as { url: string };
  // data.url is "/uploads/{filename}".
  // In Tauri: prepend the sidecar base URL so the WebView can fetch it directly.
  // In web builds: prepend /api so the Next.js proxy forwards it correctly.
  return `${BASE_URL}${data.url}`;
}
