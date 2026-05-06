import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a self-contained build in .next/standalone — required for the
  // Docker image so node_modules don't need to be copied in full.
  output: "standalone",
  allowedDevOrigins: ["192.168.68.59"],
  devIndicators: {
    position: "bottom-right",
  },
  // Proxy all /api/* requests to the FastAPI backend.
  // This keeps cookies same-origin so SameSite=Lax refresh cookies work.
  // Set API_URL (server-side only) to the backend address visible from this
  // server process — defaults to localhost:8000 for local dev.
  // /api/* is handled by the catch-all Route Handler at app/api/[...path]/route.ts,
  // which proxies requests to the FastAPI backend. No rewrites needed.
};

export default nextConfig;
