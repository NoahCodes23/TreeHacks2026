import { NextRequest } from "next/server";

const API_URL = process.env.WORLDPLAY_API_URL!;

export async function POST(req: NextRequest) {
  const body = await req.json();

  const upstream = await fetch(`${API_URL}/generate/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    const text = await upstream.text();
    return new Response(text, { status: upstream.status });
  }

  const data = await upstream.json();
  return Response.json(data);
}
