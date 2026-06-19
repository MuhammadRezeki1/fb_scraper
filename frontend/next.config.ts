import type { NextConfig } from "next";
import path from "path";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8003";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${API_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
