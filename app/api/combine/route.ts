import { NextRequest } from "next/server";
import { exec } from "child_process";
import { writeFile, readFile, unlink, mkdtemp } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";

/**
 * POST /api/combine
 * Body: { video_url: string, audio_url: string }
 *
 * Downloads both files and uses ffmpeg to mux them into a single MP4.
 * Returns the combined MP4 as binary.
 */
export async function POST(req: NextRequest) {
  let dir: string | null = null;

  try {
    const body = await req.json();
    const { audio_url, video_base64 } = body;
    let { video_url } = body;

    if ((!video_url && !video_base64) || !audio_url) {
      return Response.json(
        { error: "audio_url and either video_url or video_base64 are required" },
        { status: 400 }
      );
    }

    // Resolve relative URLs using the request origin
    const origin = req.nextUrl.origin;
    if (video_url && video_url.startsWith("/")) {
      video_url = `${origin}${video_url}`;
    }
    const resolvedAudioUrl = audio_url.startsWith("/")
      ? `${origin}${audio_url}`
      : audio_url;

    dir = await mkdtemp(join(tmpdir(), "combine-"));
    const videoPath = join(dir, "video.mp4");
    const audioPath = join(dir, "audio.mp3");
    const outputPath = join(dir, "combined.mp4");

    // Write video from base64 or download it
    if (video_base64) {
      await writeFile(videoPath, Buffer.from(video_base64, "base64"));
    }

    // Download audio (and video if not from base64) in parallel
    const fetches: Promise<Response>[] = [fetch(resolvedAudioUrl)];
    if (!video_base64) {
      fetches.push(fetch(video_url));
    }

    const results = await Promise.all(fetches);
    const audioRes = results[0];
    const videoRes = results[1]; // may be undefined if video came from base64

    if (!audioRes.ok) {
      return Response.json({ error: "Failed to download audio" }, { status: 502 });
    }
    if (videoRes && !videoRes.ok) {
      return Response.json({ error: "Failed to download video" }, { status: 502 });
    }

    const audioBuf = await audioRes.arrayBuffer();
    await writeFile(audioPath, Buffer.from(audioBuf));

    if (videoRes) {
      const videoBuf = await videoRes.arrayBuffer();
      await writeFile(videoPath, Buffer.from(videoBuf));
    }

    // Combine: skip 60s into the audio (the music gets more interesting
    // after the intro), copy both streams without re-encoding for speed.
    // -ss before -i = input-seeking (near-instant, no decode).
    // -c:v copy -c:a copy = pure remux, no re-encode.
    // -shortest = stop when the video (shorter stream) ends.
    await runFfmpeg(
      `ffmpeg -y -i "${videoPath}" -ss 60 -i "${audioPath}" -c:v copy -c:a copy -shortest -movflags +faststart "${outputPath}"`
    );

    const combined = await readFile(outputPath);

    // Cleanup
    await Promise.all([
      unlink(videoPath).catch(() => {}),
      unlink(audioPath).catch(() => {}),
      unlink(outputPath).catch(() => {}),
    ]);

    return new Response(combined, {
      headers: {
        "Content-Type": "video/mp4",
        "Content-Disposition": 'attachment; filename="combined.mp4"',
      },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";

    if (msg.includes("ffmpeg") || msg.includes("not found") || msg.includes("ENOENT")) {
      return Response.json(
        { error: "ffmpeg is not installed on the server" },
        { status: 501 }
      );
    }

    return Response.json({ error: msg }, { status: 500 });
  }
}

function runFfmpeg(cmd: string): Promise<string> {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout: 60_000 }, (err, stdout, stderr) => {
      if (err) reject(new Error(stderr || err.message));
      else resolve(stdout);
    });
  });
}
