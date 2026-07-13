import type { NextConfig } from "next";

// /api/* is proxied to the backend by src/app/api/[...path]/route.ts, which
// reads API_URL at runtime (works with any hosting; cookie stays first-party).
const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
