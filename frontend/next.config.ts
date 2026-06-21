import type { NextConfig } from "next";
import path from "path";

const BACKEND_API_URL = process.env.BACKEND_API_URL ?? process.env.NEXT_PUBLIC_API_URL;

if (!BACKEND_API_URL) {
  throw new Error("BACKEND_API_URL is required for Next.js API rewrites.");
}

const API_URL = BACKEND_API_URL.replace(/\/$/, "");

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
