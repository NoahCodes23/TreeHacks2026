import { NextRequest } from "next/server";

const API_URL = process.env.WORLDPLAY_API_URL!;

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const upstream = await fetch(`${API_URL}/download/${id}`);

  if (!upstream.ok) {
    return new Response("Video not found", { status: upstream.status });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "video/mp4",
      "Content-Disposition": `attachment; filename="${id}.mp4"`,
    },
  });
}
