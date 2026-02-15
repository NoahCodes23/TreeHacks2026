// HY-WorldPlay API types — mirrors the Pydantic models in modal_app.py

export interface VideoGenerateRequest {
    /** Base64-encoded input image (PNG or JPEG) */
    image_base64: string;
    /** Scene description (1-2000 chars) */
    prompt: string;
    /** Camera trajectory, e.g. "w-31" (forward), "s-15, right-8" */
    pose?: string;
    /** Number of video frames (must satisfy ((v-1)//4+1) % 4 == 0) */
    num_frames?: number;
    /** Video width in pixels */
    width?: number;
    /** Video height in pixels */
    height?: number;
    /** Random seed for reproducibility */
    seed?: number;
    /** Diffusion denoising steps (4 for distilled model) */
    num_inference_steps?: number;
    /** Output frames per second */
    fps?: number;
}

/** Sent to /generate/control to change pose mid-generation */
export interface VideoControlRequest {
    job_id: string;
    pose: string;
}

// ── SSE event payloads ──────────────────────────────────────────

export type GenerationStatus =
    | "starting"
    | "loading"
    | "generating"
    | "encoding"
    | "complete"
    | "error";

export interface SSEStatusEvent {
    status: GenerationStatus;
    message: string;
    job_id?: string;
}

export interface SSEProgressEvent {
    step: number;
    total_steps: number;
    chunk: number;
    total_chunks: number;
    /** 0-100 */
    percentage: number;
}

export interface SSEFrameEvent {
    /** Base64-encoded JPEG frame */
    frame_base64: string;
    /** Frame index in the full video */
    frame_index: number;
    /** Total expected frames */
    total_frames: number;
}

export interface SSECompleteEvent {
    video_base64: string;
    job_id: string;
    /** Relative path, e.g. "/download/<job_id>" */
    download_url: string;
    size_bytes: number;
}

export interface SSEErrorEvent {
    error: string;
    details?: string;
}

export type SSEEvent =
    | { type: "status"; data: SSEStatusEvent }
    | { type: "progress"; data: SSEProgressEvent }
    | { type: "frame"; data: SSEFrameEvent }
    | { type: "complete"; data: SSECompleteEvent }
    | { type: "error"; data: SSEErrorEvent };

// ── Client-side state ───────────────────────────────────────────

export interface VideoGenerationState {
    status: GenerationStatus | "idle";
    progress: number;
    currentChunk: number;
    totalChunks: number;
    /** Latest frame received during generation (base64 JPEG) */
    currentFrame: string | null;
    /** Total frames received so far */
    frameCount: number;
    videoBase64: string | null;
    videoUrl: string | null;
    jobId: string | null;
    error: string | null;
    isGenerating: boolean;
}

// ── Constants ───────────────────────────────────────────────────

export const POSE_PRESETS = {
    FORWARD: "w-31",
    BACKWARD: "s-31",
    LEFT: "a-31",
    RIGHT: "d-31",
    PAN_LEFT: "left-31",
    PAN_RIGHT: "right-31",
    LOOK_UP: "up-31",
    LOOK_DOWN: "down-31",
} as const;

export type PosePreset = (typeof POSE_PRESETS)[keyof typeof POSE_PRESETS];

export const DEFAULT_CONFIG = {
    pose: "w-31",
    num_frames: 61,
    width: 832,
    height: 480,
    seed: 42,
    num_inference_steps: 4,
    fps: 12,
} as const;
