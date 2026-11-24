import type { NextConfig } from "next";

// The browser talks to the API through this origin (/api/* is rewritten to Django), so
// the refresh cookie is first-party and SameSite=Strict works without CORS.
const apiOrigin = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  allowedDevOrigins: ["10.0.0.161"],
  experimental: {
    agentFeedback: true,
  },
  // Every screen is behind sign-in and fetches its data in the browser with TanStack
  // Query, so prerendered static shells (cacheComponents) add nothing here.
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Django URLs end in "/" (APPEND_SLASH). Next strips trailing slashes by default
  // (308 /x/ -> /x), so POSTs reached Django without the slash and failed. Keep the
  // slash: skip the redirect and forward the slashed path as-is.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      { source: "/api/:path*/", destination: `${apiOrigin}/api/:path*/` },
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
