import type { NextConfig } from "next";

// In Docker Compose the backend is reachable at http://backend:8000; in local
// dev (next dev + uvicorn) it runs on localhost. Same-origin /api rewrites
// keep the session cookie first-party.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
