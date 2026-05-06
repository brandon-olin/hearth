import createClient from "openapi-fetch";
import type { paths } from "./schema";
import { getAccessToken } from "@/lib/auth/token";

// Requests go to /api/* on the same origin, which Next.js proxies to the
// backend. This keeps cookies same-site so SameSite=Lax refresh tokens work
// regardless of where the frontend and backend are hosted.
export const apiClient = createClient<paths>({
  baseUrl: "/api",
  credentials: "same-origin",
});

apiClient.use({
  onRequest({ request }) {
    const token = getAccessToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
});
