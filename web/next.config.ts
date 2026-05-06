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
