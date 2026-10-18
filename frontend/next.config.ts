import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.0.13", "127.0.0.1"],
  experimental: {
    optimizePackageImports: [
      "@paper-design/shaders-react",
      "@paper-design/shaders",
    ],
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // No other website may frame these pages, so it cannot trick the owner into clicking
          // Confirm on a page it draws over.
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
        ],
      },
    ];
  },
};

export default nextConfig;
