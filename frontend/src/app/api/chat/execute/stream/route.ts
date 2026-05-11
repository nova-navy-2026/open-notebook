import { NextRequest } from "next/server";

// Force Node.js runtime so we get a real ReadableStream that is piped
// directly back to the client without buffering. Edge runtime would also
// work but Node matches the rest of the deployment.
export const runtime = "nodejs";
// Disable static optimization / caching for this SSE endpoint.
export const dynamic = "force-dynamic";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL || "http://localhost:5055";

/**
 * Streaming proxy for `POST /api/chat/execute/stream`.
 *
 * The default Next.js `rewrites()` proxy buffers Server-Sent Events, which
 * makes the chat appear to "spawn all at once" instead of token-by-token.
 * Route Handlers take precedence over rewrites and let us forward the raw
 * `ReadableStream` body of the FastAPI response untouched.
 */
export async function POST(req: NextRequest) {
  const upstream = await fetch(`${INTERNAL_API_URL}/api/chat/execute/stream`, {
    method: "POST",
    headers: {
      "Content-Type": req.headers.get("content-type") ?? "application/json",
      ...(req.headers.get("authorization")
        ? { Authorization: req.headers.get("authorization") as string }
        : {}),
    },
    body: req.body,
    // Required by undici when the request body is a stream.
    // @ts-expect-error - duplex is valid on Node fetch but missing from lib.dom types
    duplex: "half",
    cache: "no-store",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
