import createClient from "openapi-fetch";
import type { paths } from "./schema";
import { getAccessToken } from "@/lib/auth/token";

export const apiClient = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  credentials: "include",
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
