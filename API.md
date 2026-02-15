# Treehacks Backend API Documentation

A REST API for AI-powered music generation using Suno AI, with image-to-music capabilities powered by Claude Sonnet.

## Base URL

```
http://localhost:3000
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUNO_API_KEY` | API token for Suno music generation | Yes |
| `ANTHROPIC_API_KEY` | API key for Claude AI (image analysis) | Yes |

---

## Endpoints

### Health Check

#### `GET /`

Simple health check endpoint.

**Response:**
```
Hello Elysia
```

---

### Generate Music

#### `POST /generate`

Submit a music generation request to Suno AI.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | No | Description of the music topic/theme |
| `tags` | string | No | Space-separated tags describing music style (e.g., "ambient peaceful piano") |
| `negative_tags` | string | No | Tags to avoid in generation |
| `prompt` | string | No | Custom lyrics or detailed prompt |
| `make_instrumental` | boolean | No | If true, generates instrumental music without vocals |
| `cover_clip_id` | string | No | ID of an existing clip to create a cover of |

**Example Request:**
```bash
curl -X POST http://localhost:3000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "tags": "ambient acoustic folk peaceful serene",
    "make_instrumental": true,
    "topic": "A gentle, warm acoustic piece with flowing melodies"
  }'
```

**Response:**
```json
{
  "id": "clip_abc123",
  "request_id": "req_xyz789",
  "created_at": "2026-02-14T10:00:00Z",
  "status": "submitted",
  "title": "Generated Track",
  "metadata": {
    "tags": "ambient acoustic folk peaceful serene",
    "prompt": null,
    "gpt_description_prompt": "A gentle, warm acoustic piece...",
    "type": "generation"
  }
}
```

---

### Get Clip Status

#### `GET /clips/:id`

Get the current status and details of a generated clip.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | The clip ID returned from generation |

**Example Request:**
```bash
curl http://localhost:3000/clips/clip_abc123
```

**Response:**
```json
{
  "id": "clip_abc123",
  "request_id": "req_xyz789",
  "created_at": "2026-02-14T10:00:00Z",
  "status": "complete",
  "title": "Generated Track",
  "audio_url": "https://cdn.suno.com/audio/clip_abc123.mp3",
  "image_url": "https://cdn.suno.com/images/clip_abc123.jpg",
  "image_large_url": "https://cdn.suno.com/images/clip_abc123_large.jpg",
  "metadata": {
    "duration": 120,
    "tags": "ambient acoustic folk peaceful serene",
    "prompt": null,
    "gpt_description_prompt": "A gentle, warm acoustic piece...",
    "type": "generation"
  }
}
```

**Status Values:**

| Status | Description |
|--------|-------------|
| `submitted` | Request has been submitted and is queued |
| `streaming` | Audio is being generated and can be streamed |
| `complete` | Generation is complete |
| `failed` | Generation failed |

---

### Generate and Stream

#### `POST /generate-stream`

Submit a generation request and wait until audio is available for streaming. This endpoint polls until the audio URL is ready.

**Request Body:** Same as `/generate`

**Example Request:**
```bash
curl -X POST http://localhost:3000/generate-stream \
  -H "Content-Type: application/json" \
  -d '{
    "tags": "electronic upbeat energetic",
    "make_instrumental": true
  }'
```

**Response:**
```json
{
  "id": "clip_abc123",
  "status": "streaming",
  "title": "Generated Track",
  "audio_url": "https://cdn.suno.com/audio/clip_abc123.mp3",
  "image_url": "https://cdn.suno.com/images/clip_abc123.jpg",
  "metadata": {
    "tags": "electronic upbeat energetic",
    "type": "generation"
  }
}
```

**Note:** This endpoint may take 30-120 seconds to respond while waiting for generation.

---

### Stream Audio

#### `GET /stream/:id`

Proxy endpoint to stream audio directly. Useful for CORS handling or custom streaming logic.

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | string | The clip ID |

**Example Request:**
```bash
curl http://localhost:3000/stream/clip_abc123 --output audio.mp3
```

**Response:**
- **Success (200):** Returns audio stream with `Content-Type: audio/mpeg`
- **Not Ready (202):** Returns JSON with current status
- **Not Found (404):** No audio URL available

---

### Image to Music

#### `POST /image-to-music`

Analyze an image using Claude AI to generate music tags, then create music that matches the vibe/atmosphere of the image.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | string | Yes | Base64 encoded image or data URL (e.g., `data:image/jpeg;base64,...`) |
| `make_instrumental` | boolean | No | If true (default), generates instrumental music |

**Example Request:**
```bash
# Using a data URL
curl -X POST http://localhost:3000/image-to-music \
  -H "Content-Type: application/json" \
  -d '{
    "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
    "make_instrumental": true
  }'

# Using a file (convert to base64 first)
curl -X POST http://localhost:3000/image-to-music \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"data:image/png;base64,$(base64 -w 0 image.png)\", \"make_instrumental\": true}"
```

**Response:**
```json
{
  "id": "clip_abc123",
  "status": "streaming",
  "title": "Generated Track",
  "audio_url": "https://cdn.suno.com/audio/clip_abc123.mp3",
  "image_url": "https://cdn.suno.com/images/clip_abc123.jpg",
  "generated_tags": "ambient peaceful nature serene calm atmospheric forest morning",
  "metadata": {
    "tags": "ambient peaceful nature serene calm atmospheric forest morning",
    "type": "generation"
  }
}
```

**Notes:**
- Supported image formats: JPEG, PNG, GIF, WebP
- Generated tags are automatically truncated to 100 characters (whole tags only)
- This endpoint may take 60-180 seconds due to image analysis + music generation

---

## Error Handling

All endpoints may return error responses in the following format:

```json
{
  "error": "Error message description"
}
```

**Common HTTP Status Codes:**

| Code | Description |
|------|-------------|
| 200 | Success |
| 202 | Accepted (resource not ready yet) |
| 400 | Bad Request (invalid input) |
| 404 | Not Found |
| 500 | Internal Server Error |

---

## Usage Examples

### Generate Instrumental Music

```bash
curl -X POST http://localhost:3000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "tags": "cinematic orchestral epic dramatic",
    "make_instrumental": true,
    "topic": "An epic orchestral piece for a movie trailer"
  }'
```

### Generate Music with Lyrics

```bash
curl -X POST http://localhost:3000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "tags": "pop upbeat happy",
    "make_instrumental": false,
    "prompt": "[Verse]\nSunshine in my eyes today\nEverything will be okay\n\n[Chorus]\nWe are dancing in the light\nEverything feels so right"
  }'
```

### Poll for Completion

```bash
# Submit generation
CLIP_ID=$(curl -s -X POST http://localhost:3000/generate \
  -H "Content-Type: application/json" \
  -d '{"tags": "jazz smooth"}' | jq -r '.id')

# Poll until complete
while true; do
  STATUS=$(curl -s http://localhost:3000/clips/$CLIP_ID | jq -r '.status')
  echo "Status: $STATUS"
  if [ "$STATUS" = "complete" ] || [ "$STATUS" = "streaming" ]; then
    curl -s http://localhost:3000/clips/$CLIP_ID | jq '.audio_url'
    break
  fi
  sleep 2
done
```

---

## Rate Limits

- Suno API has rate limits based on your plan
- Claude API (for image analysis) has rate limits based on your Anthropic plan
- Consider implementing client-side rate limiting for production use

---

## Running the Server

```bash
# Install dependencies
bun install

# Set environment variables
export SUNO_API_KEY="your_suno_api_key"
export ANTHROPIC_API_KEY="your_anthropic_api_key"

# Start the server
bun run src/index.ts
```

The server will start on `http://localhost:3000`.

