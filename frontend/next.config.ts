import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.0.13", "127.0.0.1"],
  experimental: {
    optimizePackageImports: [
      "@paper-design/shaders-react",
      "@paper-design/shaders",
    ],
  },
};

export default nextConfig;
