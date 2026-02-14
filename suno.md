Welcome to the Suno API for TreeHacks 2026! This API allows you to programmatically generate music, covers, and stems using Suno's AI music models.

## Getting Started

### 1. Get Your API Key

Please have one of your team members visit the **Suno booth at TreeHacks** to receive your team’s unique API token! This token is required for all API requests and is specifically configured for TreeHacks participants. If you encounter any issues, please message Krish Chopra on Slack.

### 1.2. 🎁 Free Suno Pro + Credits

**Exclusive TreeHacks offer -** use this code for **free Suno Pro** (includes **2,500 credits**): `TREEHACKS1PRO`

To redeem, sign in and go to [suno.com/account](http://suno.com/account). Choose **Monthly**, then **Pro**, and enter the above code at checkout to receive 1 month free. Perfect for experimenting with Suno's features during and after the hackathon!

*Note*: You cannot have an active subscription before redeeming - you’ll only see the coupon area if you’re checking out from a non-subscribed state using the website!

### 1.5. Try the Starter App

Check out our **starter application** that demonstrates the song generation and polling workflow: https://github.com/suno-ai/treehacks-starter-app

This example app shows you exactly how to generate music, poll for results, and stream audio before generation is complete!

### 2. Base URL

All API endpoints are accessible at:

```
https://studio-api.prod.suno.com/api/v2/external/hackathons/
```

### 3. Authentication

All requests must include your API token in the Authorization header:

```
Authorization: Bearer YOUR_TREEHACKS_TOKEN
```

Replace `YOUR_TREEHACKS_TOKEN` with your API token (emailed to one of your team members / provided at the Suno booth).

## Rate Limits

- **Music generation**: 60 songs per minute per user
- **Stem separation**: 5 requests per minute per user
- **Clip fetching**: 100 requests per minute per user

## Audio Format & Streaming

All generated audio is provided in **MP3 format** with high-quality encoding suitable for streaming and download.

### 🎵 Real-Time Streaming

**One of Suno's coolest features!** You don't have to wait for generation to complete:

1. **Submit generation** → Get back a clip ID
2. **Poll for status** (~30 seconds) → When `status` becomes `"streaming"`, `audio_url` is available
3. **Start playing immediately** → The song streams in real-time as it generates
4. **Keep listening** → Audio continues seamlessly until the full song is complete (~1-2 minutes total)

Perfect for quick feedback and testing during your hackathon demo! 🚀

## Suno API Features for TreeHacks

- ✅ Music generation (simple and custom mode)
- ✅ Cover generation (remake songs in different styles)
- ✅ Stem separation (extract individual vocals/instruments from songs)
- ✅ Real-time generation status updates

---

## API Endpoints

### 1. Generate Music

Generate new music using either simple prompts or custom lyrics.

**Endpoint:**

```
POST /generate
```

**Request Body:**

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `topic` | string | No | A description of the song for simple mode. Max 500 characters. |
| `tags` | string | No | Musical style (genres, instruments, moods). Max 100 characters. |
| `negative_tags` | string | No | Styles or elements to avoid in generation. Max 100 characters. |
| `prompt` | string | No | Custom lyrics for the song. Use for custom mode. |
| `make_instrumental` | boolean | No | Generate instrumental version without vocals. Default: false |
| `cover_clip_id` | string | No | UUID of existing clip to create a cover version |

### Simple Mode Example

Let Suno generate lyrics and style based on your description:

```json
{
  "topic": "An upbeat pop song about coding at TreeHacks",
  "tags": "pop, electronic, upbeat, energetic"
}
```

### Custom Mode Example

Provide your own lyrics and style:

```json
{
  "prompt": "[Verse]\\nCoding through the night\\nAt TreeHacks we unite\\nBuilding dreams in code\\n\\n[Chorus]\\nHack the world, make it bright\\nInnovation takes its flight",
  "tags": "pop rock, guitar, drums, inspiring"
}
```

### Cover Generation Example

Create a new version of an existing song:

```json
{
  "cover_clip_id": "abc-123-def-456",
  "tags": "jazz, piano, saxophone, smooth"
}
```

**Response:**
Returns a single clip object:

```json
{
  "id": "31f7d8f7-f29a-4931-9695-809236ec31c0",
  "request_id": "53884401-952e-42ca-b878-8ff519e77702",
  "created_at": "2025-09-12T22:40:23.627Z",
  "status": "submitted",
  "title": "",
  "metadata": {
    "tags": "pop, upbeat",
    "prompt": "",
    "gpt_description_prompt": "A test song for TreeHacks song generation\\n\\npop, upbeat",
    "type": "gen"
  }
}
```

**Credit Cost:** 5 credits per song generation (including covers).

💡 **Note:** Use the `id` to poll the `/clips` endpoint for streaming audio URL and generation progress.

### 2. Get Clips (Check Status & Get Audio URL)

Retrieve the status and results of your generated clips. **This is how you get the audio URL once generation is complete.**

**Endpoint:**

```
GET /clips
```

**Query Parameters:**

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `ids` | string | Yes | Comma-separated list of clip UUIDs |

**Example Request:**

```
GET /clips?ids=abc-123,def-456,ghi-789
```

**Response (During Generation - Streaming Available!):**
Once status becomes `"streaming"`, the `audio_url` becomes available:

```json
[
  {
    "id": "31f7d8f7-f29a-4931-9695-809236ec31c0",
    "request_id": "53884401-952e-42ca-b878-8ff519e77702",
    "status": "streaming",
    "title": "Test Hack",
    "audio_url": "<https://audiopipe.suno.ai/?item_id=31f7d8f7-f29a-4931-9695-809236ec31c0>",
    "image_url": "<https://cdn1.suno.ai/image_31f7d8f7-f29a-4931-9695-809236ec31c0.jpeg>",
    "created_at": "2025-09-12T22:40:23.627Z",
    "metadata": {
      "tags": "song generation pop upbeat. male vocals, pop",
      "prompt": "[Verse]\\nI wish I had a home\\nMade of starlight..."
    }
  
]
```

🎵 **Real-time Streaming** - you can start playing the audio immediately when `status` is `"streaming"`! The song will continue to generate and stream in real-time.

**Response (Generation Complete):**
Once `status` is `"complete"`, the `audio_url` will contain the downloadable MP3 link:

```json
[
  {
    "id": "31f7d8f7-f29a-4931-9695-809236ec31c0",
    "request_id": "53884401-952e-42ca-b878-8ff519e77702",
    "status": "complete",
    "title": "Test Hack",
    "audio_url": "<https://cdn1.suno.ai/31f7d8f7-f29a-4931-9695-809236ec31c0.mp3>",
    "image_url": "<https://cdn1.suno.ai/image_31f7d8f7-f29a-4931-9695-809236ec31c0.jpeg>",
    "image_large_url": "<https://cdn1.suno.ai/image_large_31f7d8f7-f29a-4931-9695-809236ec31c0.jpeg>",
    "created_at": "2025-09-12T22:40:23.627Z",
    "metadata": {
      "duration": 173.6,
      "tags": "song generation pop upbeat. male vocals, pop",
      "prompt": "[Verse]\\nI wish I had a home\\nMade of starlight...",
      "gpt_description_prompt": "A test song for TreeHacks music generation\\n\\npop, upbeat",
      "type": "gen"
    }
  }
]
```

**🎵 Getting Your Audio**: Response is an **array** of clip objects.

- **During `"streaming"`**: `audio_url` provides real-time streaming (live generation)
- **During `"complete"`**: `audio_url` provides final downloadable MP3 via CDN
- **Bonus**: `title`, `image_url` (cover art for the song), and `metadata` are populated during streaming too!

### 3. Stem Separation

Split a completed song into 12 individual instrument/vocal tracks. This is great for remixing, analysis, or building creative audio experiences!

**Endpoint:**

```
POST /stem
```

**Request Body:**

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `clip_id` | string | Yes | UUID of a **completed** clip to separate into stems |

**Important:** The clip must have `status: "complete"` before you can run stem separation on it. You cannot stem-separate a clip that is still generating/streaming.

**Example Request:**

```bash
curl '<https://studio-api.prod.suno.com/api/v2/external/hackathons/stem>' \\
  -H 'Authorization: Bearer YOUR_TREEHACKS_TOKEN' \\
  -H 'Content-Type: application/json' \\
  --data-raw '{
    "clip_id": "e4ed728b-7033-4d7c-87c2-a0b635791c53"
  }'
```

**Response:**

Returns an array of 12 clip objects, one for each stem:

```json
[
  {
    "id": "3d2b3a3a-052a-4a5d-a4b7-03f166538c23",
    "request_id": "4889a1d2-edb0-4a4c-9c93-95f7ad3cd02b",
    "status": "submitted",
    "title": "My Song - Vocals",
    "created_at": "2026-02-13T19:09:30.262Z",
    "metadata": { "prompt": "", "type": "gen" }
  },
  {
    "id": "7c45dd90-ba45-4915-94d0-5f72d040c9b7",
    "status": "submitted",
    "title": "My Song - Backing Vocals",
    "..."
  }
]
```

**The 12 stems are (in order):**

| # | Stem | Description |
| --- | --- | --- |
| 1 | **Vocals** | Lead vocal track |
| 2 | **Backing Vocals** | Background/harmony vocals |
| 3 | **Drums** | Drum kit and beats |
| 4 | **Bass** | Bass guitar/synth bass |
| 5 | **Guitar** | Electric and acoustic guitar |
| 6 | **Keyboard** | Piano, keys, organ |
| 7 | **Percussion** | Shakers, tambourine, etc. |
| 8 | **Strings** | Orchestral strings |
| 9 | **Synth** | Synthesizer sounds |
| 10 | **FX** | Sound effects and ambience |
| 11 | **Brass** | Trumpet, horn, etc. |
| 12 | **Woodwinds** | Flute, clarinet, etc. |

Each stem's title follows the format: `"Original Song Title - Stem Name"`.

**Polling for Stem Results:**

Use the `/clips` endpoint with all 12 stem IDs to check their status:

```bash
curl '<https://studio-api.prod.suno.com/api/v2/external/hackathons/clips?ids=STEM_ID_1,STEM_ID_2,.>..,STEM_ID_12' \\
  -H 'Authorization: Bearer YOUR_TREEHACKS_TOKEN'
```

Stems typically take 1-2 minutes to process. Once all stems show `status: "complete"`, each will have its own `audio_url` pointing to that stem's MP3 file.

**Credit Cost:** 25 credits per stem separation request (flat rate for all 12 stems).

---

## 🔍 Understanding Response Formats

**Generate Endpoint (`/generate`):**

- Returns: **Single clip object** `{ id, request_id, status, created_at, metadata, ... }`
- Purpose: Starts a new generation
- Contains: Basic info + metadata - use the clip ID to poll for audio URL

**Stem Endpoint (`/stem`):**

- Returns: **Array of 12 clip objects** `[{ id, status, title, ... }, ...]`
- Purpose: Separates a completed clip into 12 instrument/vocal stems
- Each clip's `title` indicates which stem it is (e.g., `"Song Title - Vocals"`)
- Poll all 12 IDs via `/clips` to get audio URLs when they complete

**Clips Endpoint (`/clips?ids=...`):**

- Returns: **Array of clip objects** `[{ id, status, audio_url, ... }, ...]`
- Purpose: Check status of existing clips
- Audio URL: Available for **streaming** when `status` is `"streaming"`, final MP3 when `"complete"`

---

## Status Values

| Status | Description |
| --- | --- |
| `submitted` | Request received and queued |
| `queued` | Waiting for processing |
| `streaming` | Generation in progress - **audio_url** available for real-time streaming |
| `complete` | Generation finished - **audio_url** has final downloadable MP3 |
| `error` | Generation failed (check error_type and error_message) |

---

## Potential Workflow Example

Here's a complete example using cURL to generate a song and poll for results:

### Step 1: Generate a Song

```bash
curl '<https://studio-api.prod.suno.com/api/v2/external/hackathons/generate>' \\
  -H 'Authorization: Bearer YOUR_TREEHACKS_TOKEN' \\
  -H 'Content-Type: application/json' \\
  --data-raw '{
    "topic": "A rock anthem about hackathon innovation",
    "tags": "rock, electric guitar, powerful drums, anthem"
  }'
```

**Response:**

```json
{
  "id": "e4ed728b-7033-4d7c-87c2-a0b635791c53",
  "request_id": "a9e6129f-2117-457c-933e-e2c710d2906b",
  "status": "submitted",
  "title": "",
  "created_at": "2025-09-12T18:30:00.000Z",
  "metadata": {
    "tags": "rock, electric guitar, powerful drums, anthem",
    "gpt_description_prompt": "A rock anthem about hackathon innovation",
    "type": "gen"
  }
}
```

### Step 2: Poll for Results

**Wait 5-10 seconds**, then check the status. Keep polling until `status` becomes `"complete"`:

```bash
curl '<https://studio-api.prod.suno.com/api/v2/external/hackathons/clips?ids=e4ed728b-7033-4d7c-87c2-a0b635791c53>' \\
  -H 'Authorization: Bearer YOUR_TREEHACKS_TOKEN'
```

**Response (when polling shows streaming or complete):**

```json
[
  {
    "id": "e4ed728b-7033-4d7c-87c2-a0b635791c53",
    "request_id": "a9e6129f-2117-457c-933e-e2c710d2906b",
    "status": "complete",
    "title": "Innovation Anthem",
    "audio_url": "<https://cdn1.suno.ai/e4ed728b-7033-4d7c-87c2-a0b635791c53.mp3>",
    "image_url": "<https://cdn1.suno.ai/image_e4ed728b-7033-4d7c-87c2-a0b635791c53.jpeg>",
    "created_at": "2025-09-12T18:30:00.000Z",
    "metadata": {
      "duration": 180.5,
      "tags": "rock, electric guitar, powerful drums, anthem",
      "prompt": "[Verse]\\nBuild the future with our code...",
      "gpt_description_prompt": "A rock anthem about hackathon innovation",
      "type": "gen"
    }
  }
]
```

🎵 **Start Listening**: When `status` is `"streaming"`, the `audio_url` will be `https://audiopipe.suno.ai/?item_id=...` for real-time streaming. When `"complete"`, it becomes the final CDN MP3 URL!

### Step 3: Stream or Download

**Stream immediately** when `status` is `"streaming"`, or **download the final MP3** when `status` is `"complete"`:

```bash
curl '<https://cdn1.suno.ai/e4ed728b-7033-4d7c-87c2-a0b635791c53.mp3>' \\
  --output my_treehacks_song.mp3
```

**💡 Pro Tip**: The `audio_url` works in web players and mobile apps! During `"streaming"` it provides real-time playback, and during `"complete"` it's the final downloadable MP3.

### Step 4: Separate into Stems

Once your song is **complete**, you can split it into 12 individual instrument tracks:

```bash
curl '<https://studio-api.prod.suno.com/api/v2/external/hackathons/stem>' \\
  -H 'Authorization: Bearer YOUR_TREEHACKS_TOKEN' \\
  -H 'Content-Type: application/json' \\
  --data-raw '{
    "clip_id": "e4ed728b-7033-4d7c-87c2-a0b635791c53"
  }'
```

**Response:** An array of 12 stem clips (Vocals, Backing Vocals, Drums, Bass, Guitar, Keyboard, Percussion, Strings, Synth, FX, Brass, Woodwinds). You can poll all 12 IDs via `/clips` until they are `"complete"`, then download each stem's `audio_url`.

---

## Error Handling

### Common Error Responses

**401 Unauthorized:**

```json
{
  "detail": "Authentication required."
}
```

**403 Forbidden:**

```json
{
  "detail": "Access denied. Not a hackathon participant."
}
```

**429 Rate Limited (Generation):**

```json
{
  "detail": "Hackathon generation rate limit exceeded. Please wait before generating another song."
}
```

**400 Bad Request:**

```json
{
  "detail": "Topic too long. Please keep it under 500 characters."
}
```

### Generation Errors

If a clip fails to generate, check the `metadata.error_type` and `metadata.error_message` fields in the response.

---

## Best Practices

1. **Polling**: Check clip status every 5-10 seconds. Streaming starts in ~20-30 seconds, and song should be complete in ~1-2 minutes!
2. **Rate Limiting**: You can generate up to 60 songs per minute
3. **Error Handling**: Always check status codes and error messages
4. **Topic Length**: Keep topics under 500 characters for best results
5. **Tags**: Use descriptive genres, instruments, and moods rather than artist names
6. **Clip Completion**: Always wait for a clip to be `"complete"` before requesting stem separation
7. **Stem Polling**: When polling for stems, you can pass all 12 stem IDs in a single `/clips` request for efficiency

---

## Need Help?

Visit the **Suno booth at TreeHacks** for:

- API key troubleshooting
- Live demo and examples
- Technical support

### **Happy hacking!** 🎵