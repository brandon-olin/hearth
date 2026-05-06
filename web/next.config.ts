import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: {
    position: "bottom-right",
  },
  // Proxy all /api/* requests to the FastAPI backend.
  // This keeps cookies same-origin so SameSite=Lax refresh cookies work.
  // Set API_URL (server-side only) to the backend address visible from this
  // server process — defaults to localhost:8000 for local dev.
  async rewrites() {
    const apiUrl = process.env.API_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
