# Next.js Integration Guide

Connect your Next.js app to the HY-WorldPlay video generation API with real-time SSE streaming.

## Setup

### 1. Deploy the API

```bash
modal deploy modal_app.py
```

Modal will print a URL like:

```
https://<your-workspace>--hy-worldplay-worldplayapi-web.modal.run
```

This is your `API_BASE_URL`. Save it as an environment variable in your Next.js project:

```env
# .env.local
NEXT_PUBLIC_WORLDPLAY_API_URL=https://<your-workspace>--hy-worldplay-worldplayapi-web.modal.run
```

### 2. Copy the client files

Copy the `client/` directory into your Next.js project:

```
your-nextjs-app/
  lib/
    worldplay/
      types.ts            # from client/types.ts
      use-video-generation.ts  # from client/use-video-generation.ts
```

No additional dependencies are needed. The hook uses only `react` and the native `fetch` API.

---

## API Endpoints

| Method | Path              | Description                                  |
| ------ | ----------------- | -------------------------------------------- |
| GET    | `/health`         | Health check                                 |
| GET    | `/config`         | Available poses, defaults, and limits        |
| POST   | `/generate`       | SSE streaming endpoint (real-time progress)  |
| POST   | `/generate/sync`  | Blocking JSON endpoint (returns when done)   |
| GET    | `/download/{id}`  | Download video by job ID (10-min expiry)     |

---

## Quick Start: `useVideoGeneration` Hook

```tsx
"use client";

import { useVideoGeneration } from "@/lib/worldplay/use-video-generation";
import { POSE_PRESETS } from "@/lib/worldplay/types";
import { useRef } from "react";

const API_URL = process.env.NEXT_PUBLIC_WORLDPLAY_API_URL!;

export default function VideoGenerator() {
  const {
    status,
    progress,
    currentChunk,
    totalChunks,
    videoUrl,
    error,
    isGenerating,
    generate,
    cancel,
    reset,
  } = useVideoGeneration(API_URL);

  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleGenerate() {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    // Convert file to base64
    const buffer = await file.arrayBuffer();
    const base64 = btoa(
      new Uint8Array(buffer).reduce((s, b) => s + String.fromCharCode(b), "")
    );

    generate({
      image_base64: base64,
      prompt: "A cinematic dolly shot through a forest",
      pose: POSE_PRESETS.FORWARD,
    });
  }

  return (
    <div>
      <input ref={fileInputRef} type="file" accept="image/*" />
      <button onClick={handleGenerate} disabled={isGenerating}>
        Generate Video
      </button>
      {isGenerating && <button onClick={cancel}>Cancel</button>}

      {status !== "idle" && (
        <p>
          {status} — {progress.toFixed(1)}%
          {totalChunks > 0 && ` (chunk ${currentChunk}/${totalChunks})`}
        </p>
      )}

      {error && <p style={{ color: "red" }}>{error}</p>}

      {videoUrl && (
        <video src={videoUrl} controls autoPlay style={{ maxWidth: "100%" }} />
      )}

      {status === "complete" && <button onClick={reset}>New Video</button>}
    </div>
  );
}
```

### Hook Return Value

```ts
const {
  // State
  status,        // "idle" | "starting" | "loading" | "generating" | "encoding" | "complete" | "error"
  progress,      // 0–100
  currentChunk,  // Current autoregressive chunk being processed
  totalChunks,   // Total chunks (8 for default 125-frame config)
  videoBase64,   // Raw base64 string of the MP4 (or null)
  videoUrl,      // Full download URL (or null)
  jobId,         // Server-assigned job ID (or null)
  error,         // Error message (or null)
  isGenerating,  // true while the stream is open

  // Actions
  generate,      // (request: VideoGenerateRequest) => Promise<void>
  cancel,        // () => void  — aborts the current generation
  reset,         // () => void  — resets all state to idle
} = useVideoGeneration(apiBaseUrl);
```

---

## Request Parameters

All fields except `image_base64` and `prompt` are optional and fall back to server defaults.

```ts
interface VideoGenerateRequest {
  image_base64: string;        // Base64-encoded PNG or JPEG
  prompt: string;              // Scene description (1–2000 chars)
  pose?: string;               // Camera trajectory (default: "w-31")
  num_frames?: number;         // Frame count (default: 125)
  width?: number;              // Pixel width (default: 832)
  height?: number;             // Pixel height (default: 480)
  seed?: number;               // Random seed (default: 42)
  num_inference_steps?: number; // Denoising steps (default: 4)
  fps?: number;                // Output FPS (default: 24)
}
```

### Valid `num_frames` Values

The frame count must satisfy `((num_frames - 1) / 4 + 1) % 4 === 0`. Common valid values:

```
13, 29, 45, 61, 77, 93, 109, 125, 141, 157, ...
```

### Pose Presets

```ts
import { POSE_PRESETS } from "@/lib/worldplay/types";

POSE_PRESETS.FORWARD    // "w-31"     — dolly forward
POSE_PRESETS.BACKWARD   // "s-31"     — dolly backward
POSE_PRESETS.LEFT       // "a-31"     — strafe left
POSE_PRESETS.RIGHT      // "d-31"     — strafe right
POSE_PRESETS.PAN_LEFT   // "left-31"  — pan/yaw left
POSE_PRESETS.PAN_RIGHT  // "right-31" — pan/yaw right
POSE_PRESETS.LOOK_UP    // "up-31"    — tilt up
POSE_PRESETS.LOOK_DOWN  // "down-31"  — tilt down
```

Poses can be combined sequentially: `"w-15, right-8"` (move forward for 15 latent frames, then pan right for 8).

---

## SSE Event Types

The `/generate` endpoint streams these events:

### `status`

```json
{ "status": "generating", "message": "Starting video generation...", "job_id": "abc123" }
```

Status values flow in this order: `starting` -> `loading` -> `generating` -> `encoding` -> `complete`

### `progress`

```json
{ "step": 2, "total_steps": 4, "chunk": 3, "total_chunks": 8, "percentage": 31.3 }
```

The default config (125 frames, 4 inference steps) produces 8 chunks of 4 denoising steps each. `percentage` is the overall progress from 0 to 100.

### `complete`

```json
{
  "video_base64": "<base64 MP4>",
  "job_id": "abc123",
  "download_url": "/download/abc123",
  "size_bytes": 8421376
}
```

### `error`

```json
{ "error": "Generation failed", "details": "torchrun exit code 1" }
```

---

## Using Without the Hook

### Raw `fetch` with SSE parsing

```ts
const response = await fetch(`${API_URL}/generate`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    image_base64: "...",
    prompt: "A sunset over mountains",
    pose: "w-31",
  }),
});

const reader = response.body!.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split("\n");
  buffer = lines.pop() ?? "";

  let eventType = "";
  let dataStr = "";

  for (const line of lines) {
    if (line.startsWith("event: ")) eventType = line.slice(7).trim();
    else if (line.startsWith("data: ")) dataStr = line.slice(6);
    else if (line === "" && eventType && dataStr) {
      const data = JSON.parse(dataStr);
      console.log(eventType, data);
      // Handle each event type here
      eventType = "";
      dataStr = "";
    }
  }
}
```

### Sync endpoint (no streaming)

```ts
const response = await fetch(`${API_URL}/generate/sync`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    image_base64: "...",
    prompt: "A sunset over mountains",
  }),
});

const { video_base64, size_bytes } = await response.json();
```

### Download by job ID

After receiving a `complete` SSE event, the video is available for 10 minutes at:

```
GET {API_URL}/download/{job_id}
```

Returns raw `video/mp4` bytes.

---

## Next.js Route Handler Proxy (Optional)

If you want to keep the Modal URL private, create a proxy route in your Next.js app:

```ts
// app/api/generate/route.ts
import { NextRequest } from "next/server";

const API_URL = process.env.WORLDPLAY_API_URL!; // server-side only

export async function POST(req: NextRequest) {
  const body = await req.json();

  const upstream = await fetch(`${API_URL}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  // Forward the SSE stream directly
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
```

Then point the hook at your own route:

```ts
useVideoGeneration("/api/generate");
```

---

## Displaying the Video

### From download URL (recommended)

```tsx
{videoUrl && <video src={videoUrl} controls />}
```

### From base64 directly

```tsx
{videoBase64 && (
  <video
    src={`data:video/mp4;base64,${videoBase64}`}
    controls
  />
)}
```

### Download button

```tsx
{videoUrl && (
  <a href={videoUrl} download="worldplay.mp4">
    Download MP4
  </a>
)}
```

---

## Progress Bar Example

```tsx
function ProgressBar({ progress, status }: { progress: number; status: string }) {
  return (
    <div style={{ width: "100%", background: "#e0e0e0", borderRadius: 4, overflow: "hidden" }}>
      <div
        style={{
          width: `${progress}%`,
          height: 24,
          background: status === "error" ? "#ef4444" : "#3b82f6",
          transition: "width 0.3s ease",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "white",
          fontSize: 12,
        }}
      >
        {progress > 5 && `${progress.toFixed(0)}%`}
      </div>
    </div>
  );
}
```

---

## Troubleshooting

**CORS errors** -- The API allows all origins by default. If you see CORS issues, confirm `modal deploy` completed successfully and you're using the correct URL.

**Connection timeout** -- Video generation runs on 4x H200 GPUs and the SSE stream sends keepalive comments every 2 minutes. If your proxy or load balancer has a shorter idle timeout, the connection may drop. Increase the timeout or use the `/generate/sync` endpoint instead.

**`num_frames` validation error** -- The frame count must satisfy `((v - 1) / 4 + 1) % 4 === 0`. Use one of: 13, 29, 45, 61, 77, 93, 109, 125.

**Large video files** -- The `complete` event includes the full base64 video (can be 10-20MB encoded). For production, use `videoUrl` (the download endpoint) instead of `videoBase64` to avoid holding the full payload in memory.
