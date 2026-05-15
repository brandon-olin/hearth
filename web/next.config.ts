import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:1338";

// TAURI=1 triggers a fully static export for bundling inside the desktop app.
// The Next.js proxy and rewrites are not available in static export mode —
// the frontend talks directly to the FastAPI sidecar via NEXT_PUBLIC_API_BASE_URL.
const isTauri = process.env.TAURI === "1";

const nextConfig: NextConfig = {
  output: isTauri ? "export" : "standalone",

  // Required in Next.js 16: acknowledges that the webpack config below is
  // intentional and only runs during `next build` (Tauri export).
  // `next dev` uses Turbopack and ignores the webpack function entirely.
  turbopack: {},

  // Static export settings (Tauri build only)
  ...(isTauri && {
    // Trailing slashes ensure each route exports as dir/index.html,
    // which works better with Tauri's asset serving.
    trailingSlash: true,
    // Images can't be optimised at runtime in a static export.
    images: { unoptimized: true },
    // Disable the Next.js dev overlay in Tauri builds.
    devIndicators: false,
  }),

  // Non-Tauri settings
  ...(!isTauri && {
    allowedDevOrigins: ["192.168.68.59"],
    devIndicators: {
      position: "bottom-right",
    },
    // Proxy /uploads/* directly to the API using Next.js rewrites.
    // The catch-all proxy uses upstream.text() which corrupts binary data;
    // rewrites forward the raw bytes correctly.
    async rewrites() {
      return [
        {
          source: "/uploads/:path*",
          destination: `${API_URL}/uploads/:path*`,
        },
      ];
    },
  }),
};

export default nextConfig;
