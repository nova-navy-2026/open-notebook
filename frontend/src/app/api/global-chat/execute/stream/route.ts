import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL || "http://localhost:5055";

/**
 * Streaming proxy for `POST /api/global-chat/execute/stream`. See the sibling
 * `chat/execute/stream/route.ts` for rationale: bypasses Next.js rewrite
 * buffering so SSE deltas reach the browser as the model produces them.
 */
export async function POST(req: NextRequest) {
  const upstream = await fetch(
    `${INTERNAL_API_URL}/api/global-chat/execute/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": req.headers.get("content-type") ?? "application/json",
        ...(req.headers.get("authorization")
          ? { Authorization: req.headers.get("authorization") as string }
          : {}),
      },
      body: req.body,
      // @ts-expect-error - duplex is valid on Node fetch but missing from lib.dom types
      duplex: "half",
      cache: "no-store",
    },
  );

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
