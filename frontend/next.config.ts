import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable standalone output for optimized Docker deployment
  output: "standalone",

  // Disable Next.js gzip compression. Compressing a `text/event-stream`
  // response forces it to be buffered (the compressor accumulates bytes before
  // flushing), so SSE chat replies arrive all at once instead of streaming
  // token-by-token through the /api/* rewrite proxy. This only turns off Next's
  // own compression — static assets are still served fine and the upstream
  // reverse proxy can compress non-streaming responses if desired.
  compress: false,

  // Hosts allowed to load Next.js dev resources (HMR / webpack) when running
  // `next dev` behind a domain/reverse proxy. Without this, Next.js blocks the
  // dev assets cross-origin and the app renders a blank page. Only relevant in
  // dev mode — a production build (`next build` + `next start`) ignores this.
  allowedDevOrigins: ["marinha.novasearch.org"],

  // Pin the workspace root to this directory.
  // An orphan package-lock.json in the parent (open-notebook/) makes Next.js
  // infer the wrong root, breaking module resolution (e.g. tailwindcss).
  turbopack: {
    root: __dirname,
  },

  // Experimental features
  // Type assertion needed: proxyClientMaxBodySize is valid in Next.js 15 but types lag behind
  experimental: {
    // Increase proxy body size limit for file uploads (default is 10MB)
    // This allows larger files to be uploaded through the /api/* rewrite proxy to FastAPI
    proxyClientMaxBodySize: "100mb",
  } as NextConfig["experimental"],

  // API Rewrites: Proxy /api/* requests to FastAPI backend
  // This simplifies reverse proxy configuration - users only need to proxy to port 3675
  // Next.js handles internal routing to the API backend on port 5055
  async rewrites() {
    // INTERNAL_API_URL: Where Next.js server-side should proxy API requests
    // Default: http://localhost:5055 (single-container deployment)
    // Override for multi-container: INTERNAL_API_URL=http://api-service:5055
    const internalApiUrl =
      process.env.INTERNAL_API_URL || "http://localhost:5055";

    console.log(
      `[Next.js Rewrites] Proxying /api/* to ${internalApiUrl}/api/*`,
    );

    return [
      {
        source: "/api/:path*",
        destination: `${internalApiUrl}/api/:path*`,
      },
      // Show "/workspaces" in the browser for the Workspaces tab while still
      // serving the existing notebooks route/page. This is a URL rewrite only —
      // the address bar keeps "/workspaces" and no route directory is renamed.
      {
        source: "/workspaces",
        destination: "/notebooks",
      },
    ];
  },

  devIndicators: {
    position: "bottom-right",
  },
};

export default nextConfig;
