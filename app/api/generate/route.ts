import { NextRequest } from "next/server";

const API_URL = process.env.WORLDPLAY_API_URL!;

export async function POST(req: NextRequest) {
  const body = await req.json();

  const upstream = await fetch(`${API_URL}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, { status: upstream.status });
  }

  // Forward the SSE stream directly
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
