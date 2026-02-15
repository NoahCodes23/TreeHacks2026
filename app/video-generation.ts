import { useState, useCallback, useRef } from "react";
import type {
    VideoGenerateRequest,
    VideoGenerationState,
    SSEStatusEvent,
    SSEProgressEvent,
    SSECompleteEvent,
    SSEErrorEvent,
    GenerationStatus,
} from "./types";

const INITIAL_STATE: VideoGenerationState = {
    status: "idle",
    progress: 0,
    currentChunk: 0,
    totalChunks: 0,
    videoBase64: null,
    videoUrl: null,
    jobId: null,
    error: null,
    isGenerating: false,
};

/**
 * React hook for streaming video generation from the WorldPlayAPI.
 *
 * @example
 * ```tsx
 * const { status, progress, videoUrl, generate, cancel, reset } =
 *   useVideoGeneration("https://your-modal-app--worldplayapi-web.modal.run");
 *
 * // Start generation
 * generate({ image_base64: "...", prompt: "A forest path" });
 *
 * // Show progress
 * <p>{status} — {progress}%</p>
 *
 * // Play result
 * {videoUrl && <video src={videoUrl} controls />}
 * ```
 */
export function useVideoGeneration(apiBaseUrl: string) {
    const [state, setState] = useState<VideoGenerationState>(INITIAL_STATE);
    const abortRef = useRef<AbortController | null>(null);

    const generate = useCallback(
        async (request: VideoGenerateRequest) => {
            abortRef.current?.abort();
            const controller = new AbortController();
            abortRef.current = controller;

            setState({ ...INITIAL_STATE, status: "starting", isGenerating: true });

            try {
                const res = await fetch(`${apiBaseUrl}/generate`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(request),
                    signal: controller.signal,
                });

                if (!res.ok) {
                    const body = await res.text();
                    throw new Error(`HTTP ${res.status}: ${body}`);
                }

                const reader = res.body?.getReader();
                if (!reader) throw new Error("No response body");

                const decoder = new TextDecoder();
                let buffer = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });

                    // Parse SSE frames out of the buffer
                    let eventType = "";
                    let dataStr = "";
                    const lines = buffer.split("\n");
                    // Keep the last (possibly incomplete) line in the buffer
                    buffer = lines.pop() ?? "";

                    for (const line of lines) {
                        if (line.startsWith("event: ")) {
                            eventType = line.slice(7).trim();
                        } else if (line.startsWith("data: ")) {
                            dataStr = line.slice(6);
                        } else if (line === "" && eventType && dataStr) {
                            _dispatch(eventType, dataStr, apiBaseUrl, setState);
                            eventType = "";
                            dataStr = "";
                        }
                    }
                }

                // If stream ended without a terminal event, mark done
                setState((prev) =>
                    prev.isGenerating ? { ...prev, isGenerating: false } : prev
                );
            } catch (err) {
                if ((err as Error).name !== "AbortError") {
                    setState((prev) => ({
                        ...prev,
                        status: "error",
                        error: (err as Error).message,
                        isGenerating: false,
                    }));
                }
            }
        },
        [apiBaseUrl]
    );

    const cancel = useCallback(() => {
        abortRef.current?.abort();
        setState((prev) => ({ ...prev, isGenerating: false, status: "idle" }));
    }, []);

    const reset = useCallback(() => {
        abortRef.current?.abort();
        setState(INITIAL_STATE);
    }, []);

    return { ...state, generate, cancel, reset };
}

// ── internal ────────────────────────────────────────────────────

function _dispatch(
    eventType: string,
    dataStr: string,
    apiBaseUrl: string,
    setState: React.Dispatch<React.SetStateAction<VideoGenerationState>>
) {
    let parsed: unknown;
    try {
        parsed = JSON.parse(dataStr);
    } catch {
        return; // skip malformed data
    }

    switch (eventType) {
        case "status": {
            const d = parsed as SSEStatusEvent;
            setState((prev) => ({
                ...prev,
                status: d.status as GenerationStatus,
                jobId: d.job_id ?? prev.jobId,
            }));
            break;
        }
        case "progress": {
            const d = parsed as SSEProgressEvent;
            setState((prev) => ({
                ...prev,
                progress: d.percentage,
                currentChunk: d.chunk,
                totalChunks: d.total_chunks,
            }));
            break;
        }
        case "complete": {
            const d = parsed as SSECompleteEvent;
            setState((prev) => ({
                ...prev,
                status: "complete",
                progress: 100,
                videoBase64: d.video_base64,
                videoUrl: `${apiBaseUrl}${d.download_url}`,
                jobId: d.job_id,
                isGenerating: false,
            }));
            break;
        }
        case "error": {
            const d = parsed as SSEErrorEvent;
            setState((prev) => ({
                ...prev,
                status: "error",
                error: d.error,
                isGenerating: false,
            }));
            break;
        }
    }
}
