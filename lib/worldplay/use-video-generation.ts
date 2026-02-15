import { useState, useCallback, useRef } from "react";
import type {
    VideoGenerateRequest,
    VideoGenerationState,
    SSEStatusEvent,
    SSEProgressEvent,
    SSEFrameEvent,
    SSECompleteEvent,
    SSEErrorEvent,
    GenerationStatus,
} from "./types";

const INITIAL_STATE: VideoGenerationState = {
    status: "idle",
    progress: 0,
    currentChunk: 0,
    totalChunks: 0,
    currentFrame: null,
    frameCount: 0,
    videoBase64: null,
    videoUrl: null,
    jobId: null,
    error: null,
    isGenerating: false,
};

/**
 * React hook for streaming video generation with live frame preview
 * and real-time pose control.
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
                // These MUST persist across read() calls — a single SSE
                // event (especially `complete` with its large video_base64)
                // will span many chunks.
                let eventType = "";
                let dataStr = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });

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

    /** Send a pose change to an in-progress generation */
    const sendControl = useCallback(
        async (pose: string) => {
            const jobId = state.jobId;
            if (!jobId || !state.isGenerating) return;

            try {
                await fetch(`${apiBaseUrl}/generate/control`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ job_id: jobId, pose }),
                });
            } catch {
                // Control messages are best-effort; don't break the stream
            }
        },
        [apiBaseUrl, state.jobId, state.isGenerating]
    );

    const cancel = useCallback(() => {
        abortRef.current?.abort();
        setState((prev) => ({ ...prev, isGenerating: false, status: "idle" }));
    }, []);

    const reset = useCallback(() => {
        abortRef.current?.abort();
        setState(INITIAL_STATE);
    }, []);

    return { ...state, generate, sendControl, cancel, reset };
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
        return;
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
        case "frame": {
            const d = parsed as SSEFrameEvent;
            setState((prev) => ({
                ...prev,
                currentFrame: d.frame_base64,
                frameCount: d.frame_index + 1,
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
