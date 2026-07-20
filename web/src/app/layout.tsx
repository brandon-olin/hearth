import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { TauriRscPatch } from "@/components/tauri-rsc-patch";
import { ServiceWorkerRegister } from "@/components/service-worker-register";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });

export const metadata: Metadata = {
  title: "Hearth",
  description: "Brandon's household life management system",
  manifest: "/manifest.json",
  applicationName: "Hearth",
  appleWebApp: {
    capable: true,
    title: "Hearth",
    // "default" keeps the iOS status bar legible against the app background.
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // viewport-fit=cover lets the app draw into the iOS safe areas in standalone mode.
  viewportFit: "cover",
  themeColor: "#1c1412",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${geist.variable} h-full`} suppressHydrationWarning>
      <body className="h-full bg-background text-foreground antialiased">
        <Providers>
          <TauriRscPatch />
          <ServiceWorkerRegister />
          {children}
        </Providers>
      </body>
    </html>
  );
}
