import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // The browser only ever talks to this origin; /api is proxied to FastAPI so the session cookie is first-party.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  compress: false, // keep tutor SSE streams unbuffered through the proxy
};

export default nextConfig;
