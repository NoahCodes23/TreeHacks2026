import Elysia, { t } from "elysia";
import Anthropic from "@anthropic-ai/sdk";

const SUNO_API_BASE = "https://studio-api.prod.suno.com/api/v2/external/hackathons";
const SUNO_API_TOKEN = process.env.SUNO_API_KEY;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;

// Validate required environment variables
if (!ANTHROPIC_API_KEY) {
    console.error("⚠️  ANTHROPIC_API_KEY is not set in environment variables");
}
if (!SUNO_API_TOKEN) {
    console.error("⚠️  SUNO_API_KEY is not set in environment variables");
}

// Initialize Anthropic Claude
const anthropic = new Anthropic({
    apiKey: ANTHROPIC_API_KEY,
});
const CLAUDE_MODEL = "claude-sonnet-4-20250514";
console.log(`Using Claude model: ${CLAUDE_MODEL}`);

// Type definitions for Suno API

// Request interface for /generate endpoint
interface GenerateRequest {
    topic?: string;
    tags?: string;
    negative_tags?: string;
    prompt?: string;
    make_instrumental?: boolean;
    cover_clip_id?: string;
}

// Response interface for /generate endpoint
interface GenerateResponse {
    id: string;
    request_id: string;
    created_at: string;
    status: "submitted";
    title: string;
    metadata: {
        tags?: string;
        prompt?: string;
        gpt_description_prompt?: string;
        type?: string;
    };
}

// Response interface for /clips endpoint
interface ClipResponse {
    id: string;
    request_id: string;
    created_at: string;
    status: "submitted" | "streaming" | "complete" | "failed";
    title: string;
    audio_url?: string;
    image_url?: string;
    image_large_url?: string;
    metadata: {
        duration?: number;
        tags?: string;
        prompt?: string;
        gpt_description_prompt?: string;
        type?: string;
    };
}

// Helper function to generate music
async function generateMusic(request: GenerateRequest): Promise<GenerateResponse> {
    const response = await fetch(`${SUNO_API_BASE}/generate`, {
        method: "POST",
        headers: {
            "Authorization": `Bearer ${SUNO_API_TOKEN}`,
            "Content-Type": "application/json",
        },
        body: JSON.stringify(request),
    });

    if (!response.ok) {
        console.log(`Suno API error details: ${await response.text()}`);
        throw new Error(`Suno API error: ${response.status} ${response.statusText}`);
    }

    return response.json();
}

// Helper function to get clip status
async function getClipStatus(clipId: string): Promise<ClipResponse[]> {
    const response = await fetch(`${SUNO_API_BASE}/clips?ids=${clipId}`, {
        method: "GET",
        headers: {
            "Authorization": `Bearer ${SUNO_API_TOKEN}`,
        },
    });

    if (!response.ok) {
        throw new Error(`Suno API error: ${response.status} ${response.statusText}`);
    }

    return response.json();
}

// Helper function to poll until streaming or complete
async function pollForAudio(clipId: string, maxAttempts = 60, intervalMs = 2000): Promise<ClipResponse> {
    for (let i = 0; i < maxAttempts; i++) {
        const clips = await getClipStatus(clipId);
        const clip = clips[0];

        if (clip.status === "streaming" || clip.status === "complete") {
            return clip;
        }

        if (clip.status === "failed") {
            throw new Error("Music generation failed");
        }

        await new Promise(resolve => setTimeout(resolve, intervalMs));
    }

    throw new Error("Timeout waiting for music generation");
}

// Helper function to truncate tags to fit within maxLength characters
// Removes entire tags (not partial) to stay under the limit
function truncateTags(tags: string, maxLength: number = 100): string {
    if (tags.length <= maxLength) {
        return tags;
    }

    const tagArray = tags.split(" ");
    let result = "";

    for (const tag of tagArray) {
        const newResult = result ? `${result} ${tag}` : tag;
        if (newResult.length <= maxLength) {
            result = newResult;
        } else {
            break;
        }
    }

    return result;
}

// Helper function to analyze image and generate music tags using Claude
async function analyzeImageForMusicTags(imageData: string, mimeType: string): Promise<string> {
    const prompt = `Analyze this image and generate space-separated tags for music that would fit the vibe, environment, or setting of this image. 
    
The tags should describe musical genres, instruments, moods, and atmospheres that match the image.
Output ONLY the tags, nothing else. No explanations, no punctuation except spaces between tags.
Keep tags concise and relevant for an AI music generator.
Example output: ambient peaceful piano nature serene calm atmospheric

Generate tags for this image:`;

    const response = await anthropic.messages.create({
        model: CLAUDE_MODEL,
        max_tokens: 200,
        messages: [
            {
                role: "user",
                content: [
                    {
                        type: "image",
                        source: {
                            type: "base64",
                            media_type: mimeType as "image/jpeg" | "image/png" | "image/gif" | "image/webp",
                            data: imageData,
                        },
                    },
                    {
                        type: "text",
                        text: prompt,
                    },
                ],
            },
        ],
    });

    // Extract text from response
    const textContent = response.content.find(block => block.type === "text");
    const tags = textContent && textContent.type === "text" ? textContent.text.trim().toLowerCase() : "";

    // Truncate to 100 characters, removing whole tags
    return truncateTags(tags, 100);
}

const app = new Elysia()
    .get("/", () => "Hello Elysia")

    // Generate music endpoint - simple mode
    .post("/generate", async ({ body }) => {
        return await generateMusic(body);
    }, {
        body: t.Object({
            topic: t.Optional(t.String()),
            tags: t.Optional(t.String()),
            negative_tags: t.Optional(t.String()),
            prompt: t.Optional(t.String()),
            make_instrumental: t.Optional(t.Boolean()),
            cover_clip_id: t.Optional(t.String()),
        }),
    })

    // Get clip status endpoint
    .get("/clips/:id", async ({ params }) => {
        const clips = await getClipStatus(params.id);
        return clips[0];
    }, {
        params: t.Object({
            id: t.String(),
        }),
    })

    // Generate and stream - returns as soon as audio is available for streaming
    .post("/generate-stream", async ({ body }) => {
        // Step 1: Submit generation request
        const generated = await generateMusic(body);
        const clipId = generated.id;

        // Step 2: Poll until streaming status (audio becomes available)
        const clip = await pollForAudio(clipId);

        // Step 3: Return the streaming audio URL
        // The client can immediately start playing this URL
        // Audio will stream in real-time as it generates
        return {
            id: clip.id,
            status: clip.status,
            title: clip.title,
            // This URL streams audio in real-time during generation
            audio_url: clip.audio_url,
            image_url: clip.image_url,
            metadata: clip.metadata,
        };
    }, {
        body: t.Object({
            topic: t.Optional(t.String()),
            tags: t.Optional(t.String()),
            negative_tags: t.Optional(t.String()),
            prompt: t.Optional(t.String()),
            make_instrumental: t.Optional(t.Boolean()),
            cover_clip_id: t.Optional(t.String()),
        }),
    })

    // Proxy the audio stream directly (optional - for CORS or custom handling)
    .get("/stream/:id", async ({ params }) => {
        // First check if the clip is ready for streaming
        const clips = await getClipStatus(params.id);
        const clip = clips[0];

        if (clip.status !== "streaming" && clip.status !== "complete") {
            return new Response(JSON.stringify({
                error: "Audio not ready yet",
                status: clip.status
            }), {
                status: 202,
                headers: { "Content-Type": "application/json" }
            });
        }

        if (!clip.audio_url) {
            return new Response(JSON.stringify({ error: "No audio URL available" }), {
                status: 404,
                headers: { "Content-Type": "application/json" }
            });
        }

        // Proxy the audio stream from Suno
        const audioResponse = await fetch(clip.audio_url);

        return new Response(audioResponse.body, {
            headers: {
                "Content-Type": "audio/mpeg",
                "Transfer-Encoding": "chunked",
            }
        });
    }, {
        params: t.Object({
            id: t.String(),
        }),
    })

    // Image to music endpoint - analyzes image and generates music based on its vibe
    .post("/image-to-music", async ({ body }) => {
        const { image, make_instrumental } = body;

        // Extract base64 data and mime type from the image
        let imageData: string;
        let mimeType: string;

        if (image.startsWith("data:")) {
            // Handle data URL format: data:image/jpeg;base64,/9j/4AAQ...
            const matches = image.match(/^data:(.+);base64,(.+)$/);
            if (!matches) {
                throw new Error("Invalid image data URL format");
            }
            mimeType = matches[1];
            imageData = matches[2];
        } else {
            // Assume raw base64 with default mime type
            imageData = image;
            mimeType = "image/jpeg";
        }

        console.log("Analyzing image with Claude...");

        // Step 1: Analyze image and get music tags
        const tags = await analyzeImageForMusicTags(imageData, mimeType);
        console.log("Generated tags:", tags);

        // Step 2: Generate music with the tags
        const generateRequest: GenerateRequest = {
            tags: tags,
            make_instrumental: make_instrumental ?? true,
            topic: "Music inspired by the mood and atmosphere of an image",
        };

        const generated = await generateMusic(generateRequest);
        console.log("Music generation submitted, clip ID:", generated.id);

        // Step 3: Poll until audio is ready
        const clip = await pollForAudio(generated.id);
        console.log("Audio ready:", clip.audio_url);

        // Return the result with the generated tags
        return {
            id: clip.id,
            status: clip.status,
            title: clip.title,
            audio_url: clip.audio_url,
            image_url: clip.image_url,
            generated_tags: tags,
            metadata: clip.metadata,
        };
    }, {
        body: t.Object({
            image: t.String({ description: "Base64 encoded image or data URL" }),
            make_instrumental: t.Optional(t.Boolean()),
        }),
    })

    .listen(3000);

console.log(
    `🦊 Elysia is running at ${app.server?.hostname}:${app.server?.port}`
);
