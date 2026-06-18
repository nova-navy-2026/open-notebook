import { NextRequest, NextResponse } from 'next/server'

/**
 * Runtime Configuration Endpoint
 *
 * This endpoint provides server-side environment variables to the client at runtime.
 * This solves the NEXT_PUBLIC_* limitation where variables are baked into the build.
 *
 * Environment Variables:
 * - API_URL: Where the browser/client should make API requests (public/external URL)
 * - INTERNAL_API_URL: Where Next.js server-side should proxy API requests (internal URL)
 *   Default: http://localhost:5055 (used by Next.js rewrites in next.config.ts)
 *
 * Why two different variables?
 * - API_URL: Used by browser clients, can be https://your-domain.com or http://server-ip:5055
 * - INTERNAL_API_URL: Used by Next.js rewrites for server-side proxying, typically http://localhost:5055
 *
 * Resolution logic for API_URL:
 * 1. If API_URL env var is set, use it (explicit override for split-host setups)
 * 2. Otherwise, use same-origin relative requests ("/api/*") proxied by Next.js
 *    rewrites to INTERNAL_API_URL. Only the frontend port needs to be exposed.
 *
 * This allows the same Docker image to work in different deployment scenarios.
 */
export async function GET() {
  // Priority 1: Check if API_URL is explicitly set
  const envApiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL

  if (envApiUrl) {
    return NextResponse.json({
      apiUrl: envApiUrl,
    })
  }

  // Priority 2: Use same-origin relative requests (zero-config default).
  //
  // The browser calls "/api/*" on whatever origin it loaded the app from, and
  // Next.js rewrites (see next.config.ts) proxy that to INTERNAL_API_URL
  // (localhost:5055) server-side. This is the intended deployment model: only
  // the frontend port (e.g. 3675) needs to be exposed / reverse-proxied.
  //
  // We deliberately do NOT auto-build "<host>:5055": behind a reverse proxy
  // (e.g. https://marinha.novasearch.org) port 5055 is not reachable from the
  // browser, so that URL would hang every request and leave the app on a blank
  // page. An empty apiUrl makes the client use relative "/api" paths instead.
  // For deployments that expose the API on a separate public URL, set API_URL.
  return NextResponse.json({
    apiUrl: '',
  })
}
