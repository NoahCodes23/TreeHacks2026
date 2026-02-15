"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useVideoGeneration } from "@/lib/worldplay/use-video-generation";
import { POSE_PRESETS, type PosePreset } from "@/lib/worldplay/types";

// ── Types ─────────────────────────────────────────────────────────

interface ClipStatus {
  id: string;
  status: "submitted" | "streaming" | "complete" | "failed";
  title?: string;
  audio_url?: string;
  image_url?: string;
  generated_tags?: string;
  metadata?: { tags?: string; duration?: number };
  error?: string;
}

const POSE_OPTIONS = [
  { label: "Forward", value: POSE_PRESETS.FORWARD, icon: "\u2191" },
  { label: "Backward", value: POSE_PRESETS.BACKWARD, icon: "\u2193" },
  { label: "Left", value: POSE_PRESETS.LEFT, icon: "\u2190" },
  { label: "Right", value: POSE_PRESETS.RIGHT, icon: "\u2192" },
  { label: "Pan L", value: POSE_PRESETS.PAN_LEFT, icon: "\u21B6" },
  { label: "Pan R", value: POSE_PRESETS.PAN_RIGHT, icon: "\u21B7" },
  { label: "Up", value: POSE_PRESETS.LOOK_UP, icon: "\u2197" },
  { label: "Down", value: POSE_PRESETS.LOOK_DOWN, icon: "\u2198" },
] as const;

// ── Helpers ───────────────────────────────────────────────────────

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Delay revoke so the browser has time to start the download
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function base64ToBlob(base64: string, mime: string): Blob {
  const byteChars = atob(base64);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) {
    bytes[i] = byteChars.charCodeAt(i);
  }
  return new Blob([bytes], { type: mime });
}

// ── Main Component ────────────────────────────────────────────────

export default function Home() {
  // ── Image ───────────────────────────────────────────────────
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Music ───────────────────────────────────────────────────
  const [isGeneratingMusic, setIsGeneratingMusic] = useState(false);
  const [clipStatus, setClipStatus] = useState<ClipStatus | null>(null);
  const [musicError, setMusicError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // ── Video ───────────────────────────────────────────────────
  const [videoPrompt, setVideoPrompt] = useState("");
  const [selectedPose, setSelectedPose] = useState<PosePreset>(
    POSE_PRESETS.FORWARD
  );
  const video = useVideoGeneration("/api");
  const videoRef = useRef<HTMLVideoElement>(null);

  // ── Downloads ─────────────────────────────────────────────
  const [isCombining, setIsCombining] = useState(false);
  const [combineError, setCombineError] = useState<string | null>(null);

  // ── Create local blob URL from videoBase64 for reliable playback/download
  const [videoBlobUrl, setVideoBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    if (video.videoBase64) {
      try {
        const blob = base64ToBlob(video.videoBase64, "video/mp4");
        const url = URL.createObjectURL(blob);
        setVideoBlobUrl(url);
        return () => URL.revokeObjectURL(url);
      } catch {
        setVideoBlobUrl(null);
      }
    } else {
      setVideoBlobUrl(null);
    }
  }, [video.videoBase64]);

  // The effective video URL: prefer local blob, fall back to proxy download
  const effectiveVideoUrl = videoBlobUrl ?? video.videoUrl;

  // ── Image handling ──────────────────────────────────────────

  const handleImageSelect = useCallback(
    (file: File) => {
      if (!file.type.startsWith("image/")) {
        setMusicError("Please select a valid image file");
        return;
      }
      setImageFile(file);
      setMusicError(null);
      setClipStatus(null);
      setCombineError(null);
      video.reset();

      const reader = new FileReader();
      reader.onload = (e) => setSelectedImage(e.target?.result as string);
      reader.readAsDataURL(file);
    },
    [video]
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleImageSelect(file);
  };

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) handleImageSelect(file);
    },
    [handleImageSelect]
  );

  // ── Music generation ────────────────────────────────────────

  const pollForStatus = useCallback(async (clipId: string) => {
    try {
      const response = await fetch(`/api/clips/${clipId}`);
      const data: ClipStatus = await response.json();
      setClipStatus(data);

      if (data.status === "failed") {
        setIsGeneratingMusic(false);
        setMusicError(data.error || "Music generation failed");
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        return;
      }

      if (data.status === "complete") {
        setIsGeneratingMusic(false);
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }

      if (data.audio_url && audioRef.current) {
        if (audioRef.current.src !== data.audio_url) {
          audioRef.current.src = data.audio_url;
          audioRef.current.load();
        }
      }
    } catch (err) {
      console.error("Error polling status:", err);
    }
  }, []);

  const startMusicGeneration = useCallback(
    async (imageDataUrl: string) => {
      setIsGeneratingMusic(true);
      setMusicError(null);
      setClipStatus(null);

      try {
        const response = await fetch("/api/image-to-music", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            image: imageDataUrl,
            make_instrumental: true,
          }),
        });

        const data: ClipStatus = await response.json();
        if (!response.ok)
          throw new Error(data.error || "Failed to generate music");

        setClipStatus(data);

        if (data.audio_url && audioRef.current) {
          audioRef.current.src = data.audio_url;
          audioRef.current.load();
        }

        if (data.status !== "complete") {
          pollingRef.current = setInterval(() => pollForStatus(data.id), 3000);
        } else {
          setIsGeneratingMusic(false);
        }
      } catch (err) {
        setMusicError(err instanceof Error ? err.message : "An error occurred");
        setIsGeneratingMusic(false);
      }
    },
    [pollForStatus]
  );

  // ── Video generation ────────────────────────────────────────

  const startVideoGeneration = useCallback(
    (imageDataUrl: string) => {
      const base64 = imageDataUrl.replace(/^data:image\/[^;]+;base64,/, "");
      video.generate({
        image_base64: base64,
        prompt: videoPrompt || "A cinematic camera movement through the scene",
        pose: selectedPose,
      });
    },
    [video, videoPrompt, selectedPose]
  );

  // ── Generate All (music + video simultaneously) ─────────────

  const handleGenerateAll = () => {
    if (!selectedImage || !imageFile) return;
    setCombineError(null);
    startMusicGeneration(selectedImage);
    startVideoGeneration(selectedImage);
  };

  // ── Real-time pose control ──────────────────────────────────

  const handlePoseChange = (pose: PosePreset) => {
    setSelectedPose(pose);
    if (video.isGenerating) {
      video.sendControl(pose);
    }
  };

  // ── Synchronized playback ───────────────────────────────────

  const videoComplete = video.status === "complete";
  const audioAvailable = !!clipStatus?.audio_url;

  useEffect(() => {
    if (videoComplete && audioAvailable && videoRef.current && audioRef.current) {
      const v = videoRef.current;
      const a = audioRef.current;
      v.currentTime = 0;
      a.currentTime = 0;
      const t = setTimeout(() => {
        v.play().catch(() => {});
        a.play().catch(() => {});
      }, 300);
      return () => clearTimeout(t);
    }
  }, [videoComplete, audioAvailable]);

  // ── Download handlers ───────────────────────────────────────

  const handleDownloadVideo = () => {
    // Prefer building blob directly from base64 (most reliable)
    if (video.videoBase64) {
      const blob = base64ToBlob(video.videoBase64, "video/mp4");
      downloadBlob(blob, "worldplay-video.mp4");
      return;
    }
    // Fallback: open the proxy download URL in a new tab
    if (effectiveVideoUrl) {
      window.open(effectiveVideoUrl, "_blank");
    }
  };

  const handleDownloadCombined = async () => {
    if (!clipStatus?.audio_url) return;
    if (!effectiveVideoUrl && !video.videoBase64) return;

    setIsCombining(true);
    setCombineError(null);

    try {
      const res = await fetch("/api/combine", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_base64: video.videoBase64 || null,
          video_url: video.videoUrl || null,
          audio_url: clipStatus.audio_url,
        }),
      });

      if (!res.ok) {
        let msg = "Combine failed";
        try {
          const err = await res.json();
          msg = err.error || msg;
        } catch {
          msg = await res.text();
        }
        throw new Error(msg);
      }

      const blob = await res.blob();
      downloadBlob(blob, "combined.mp4");
    } catch (err) {
      setCombineError(err instanceof Error ? err.message : "Combine failed");
    } finally {
      setIsCombining(false);
    }
  };

  const handleDownloadAudio = async () => {
    if (!clipStatus?.audio_url) return;
    try {
      const res = await fetch(clipStatus.audio_url);
      const blob = await res.blob();
      downloadBlob(blob, `${clipStatus.title || "music"}.mp3`);
    } catch {
      setMusicError("Failed to download audio");
    }
  };

  // ── Reset ───────────────────────────────────────────────────

  const resetState = () => {
    setSelectedImage(null);
    setImageFile(null);
    setClipStatus(null);
    setMusicError(null);
    setIsGeneratingMusic(false);
    setVideoPrompt("");
    setCombineError(null);
    video.reset();
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    if (audioRef.current) audioRef.current.src = "";
  };

  // ── Status helpers ──────────────────────────────────────────

  const getMusicStatusText = () => {
    if (!clipStatus) return "";
    switch (clipStatus.status) {
      case "submitted":
        return "Analyzing image and generating music...";
      case "streaming":
        return "Music streaming - you can listen now!";
      case "complete":
        return "Music complete";
      case "failed":
        return "Music generation failed";
      default:
        return "";
    }
  };

  const getVideoStatusText = () => {
    switch (video.status) {
      case "starting":
        return "Connecting to GPU cluster...";
      case "loading":
        return "Loading model weights...";
      case "generating":
        return `Generating video - chunk ${video.currentChunk}/${video.totalChunks}`;
      case "encoding":
        return "Encoding final video...";
      case "complete":
        return "Video complete";
      case "error":
        return "Video generation failed";
      default:
        return "";
    }
  };

  const isAnyGenerating = isGeneratingMusic || video.isGenerating;
  const canDownloadVideo = videoComplete && !!(effectiveVideoUrl || video.videoBase64);
  const canDownloadCombined = canDownloadVideo && !!clipStatus?.audio_url;

  // ── Render ──────────────────────────────────────────────────

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center gap-8 py-12 px-6 bg-white dark:bg-black">
        {/* Header */}
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight text-black dark:text-white mb-2">
            Image to Music & Video
          </h1>
          <p className="text-zinc-600 dark:text-zinc-400">
            Upload an image to generate synced music and cinematic video
            simultaneously
          </p>
        </div>

        {/* Image Upload */}
        <div
          className={`w-full border-2 border-dashed rounded-2xl p-8 transition-colors cursor-pointer ${
            isDragging
              ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
              : "border-zinc-300 dark:border-zinc-700 hover:border-zinc-400 dark:hover:border-zinc-600"
          }`}
          onClick={() => fileInputRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            setIsDragging(false);
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            className="hidden"
          />
          {selectedImage ? (
            <div className="flex flex-col items-center gap-4">
              <img
                src={selectedImage}
                alt="Selected"
                className="max-h-48 rounded-xl object-contain"
              />
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                Click or drag to change image
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4 py-8">
              <div className="w-16 h-16 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center">
                <svg
                  className="w-8 h-8 text-zinc-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
                  />
                </svg>
              </div>
              <p className="text-lg font-medium text-zinc-700 dark:text-zinc-300">
                Drop your image here
              </p>
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                or click to browse
              </p>
            </div>
          )}
        </div>

        {/* ── Controls (shown when image selected) ────────────── */}
        {selectedImage && (
          <>
            {/* Video Prompt */}
            <div className="w-full space-y-2">
              <label
                htmlFor="video-prompt"
                className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
              >
                Scene Prompt
              </label>
              <input
                id="video-prompt"
                type="text"
                value={videoPrompt}
                onChange={(e) => setVideoPrompt(e.target.value)}
                placeholder="A cinematic dolly shot through a forest"
                disabled={video.isGenerating}
                className="w-full px-4 py-3 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              />
            </div>

            {/* Camera Pose Grid -- interactive during generation */}
            <div className="w-full space-y-2">
              <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Camera Movement
                {video.isGenerating && (
                  <span className="ml-2 text-xs text-blue-500 font-normal">
                    (click to change in real-time)
                  </span>
                )}
              </label>
              <div className="grid grid-cols-4 gap-2">
                {POSE_OPTIONS.map((pose) => (
                  <button
                    key={pose.value}
                    onClick={() => handlePoseChange(pose.value)}
                    className={`px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                      selectedPose === pose.value
                        ? "bg-blue-600 text-white ring-2 ring-blue-400"
                        : "bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                    }`}
                  >
                    <span className="text-base">{pose.icon}</span>{" "}
                    {pose.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Generate / Cancel buttons */}
            <div className="flex flex-wrap gap-3 justify-center">
              {isAnyGenerating ? (
                <button
                  onClick={() => {
                    video.cancel();
                    if (pollingRef.current) {
                      clearInterval(pollingRef.current);
                      pollingRef.current = null;
                    }
                    setIsGeneratingMusic(false);
                  }}
                  className="px-8 py-3 rounded-full font-medium bg-red-600 text-white hover:bg-red-700 transition-colors flex items-center gap-2"
                >
                  <Spinner /> Cancel All
                </button>
              ) : (
                <>
                  <button
                    onClick={handleGenerateAll}
                    disabled={!selectedImage}
                    className={`px-8 py-3 rounded-full font-medium transition-all ${
                      !selectedImage
                        ? "bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-600 cursor-not-allowed"
                        : "bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:opacity-90"
                    }`}
                  >
                    Generate Music & Video
                  </button>
                  {(clipStatus || video.status !== "idle") && (
                    <button
                      onClick={resetState}
                      className="px-6 py-3 rounded-full font-medium border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                    >
                      Clear
                    </button>
                  )}
                </>
              )}
            </div>
          </>
        )}

        {/* ── Live Generation Panel ────────────────────────────── */}
        {(isAnyGenerating || videoComplete || clipStatus) && (
          <div className="w-full space-y-6">
            {/* Split status row */}
            <div className="grid grid-cols-2 gap-4">
              {/* Music status */}
              <div className="p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900 space-y-2">
                <div className="flex items-center gap-2">
                  <div
                    className={`w-2 h-2 rounded-full ${
                      clipStatus?.status === "complete"
                        ? "bg-green-500"
                        : clipStatus?.status === "failed"
                          ? "bg-red-500"
                          : isGeneratingMusic
                            ? "bg-green-500 animate-pulse"
                            : "bg-zinc-300 dark:bg-zinc-600"
                    }`}
                  />
                  <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Music
                  </p>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {getMusicStatusText() || "Ready"}
                </p>
              </div>

              {/* Video status */}
              <div className="p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900 space-y-2">
                <div className="flex items-center gap-2">
                  <div
                    className={`w-2 h-2 rounded-full ${
                      videoComplete
                        ? "bg-green-500"
                        : video.status === "error"
                          ? "bg-red-500"
                          : video.isGenerating
                            ? "bg-blue-500 animate-pulse"
                            : "bg-zinc-300 dark:bg-zinc-600"
                    }`}
                  />
                  <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Video
                  </p>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {getVideoStatusText() || "Ready"}
                </p>
              </div>
            </div>

            {/* Video progress bar */}
            {video.isGenerating && (
              <div className="space-y-1">
                <div className="w-full h-2 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-600 rounded-full transition-all duration-300 ease-out"
                    style={{ width: `${video.progress}%` }}
                  />
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 text-center">
                  {video.progress.toFixed(1)}%
                  {video.totalChunks > 0 &&
                    ` - chunk ${video.currentChunk}/${video.totalChunks}`}
                  {video.frameCount > 0 && ` - ${video.frameCount} frames`}
                </p>
              </div>
            )}

            {/* Live Preview (during generation) */}
            {video.isGenerating && selectedImage && (
              <div className="w-full rounded-2xl overflow-hidden bg-black relative">
                <img
                  src={
                    video.currentFrame
                      ? `data:image/jpeg;base64,${video.currentFrame}`
                      : selectedImage
                  }
                  alt="Live preview"
                  className="w-full object-contain"
                />
                <div className="absolute top-3 left-3 px-2 py-1 bg-red-600 text-white text-xs font-bold rounded">
                  {video.currentFrame ? "LIVE" : "GENERATING"}
                </div>
                {/* Progress shimmer overlay */}
                <div
                  className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent animate-shimmer pointer-events-none"
                  style={{
                    animation: "shimmer 2s ease-in-out infinite",
                  }}
                />
                {video.currentFrame && (
                  <div className="absolute bottom-3 right-3 px-2 py-1 bg-black/60 text-white text-xs rounded">
                    Frame {video.frameCount}
                  </div>
                )}
              </div>
            )}

            {/* Errors */}
            {musicError && (
              <div className="p-3 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-xl">
                <p className="text-red-600 dark:text-red-400 text-sm text-center">
                  {musicError}
                </p>
              </div>
            )}
            {video.error && (
              <div className="p-3 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-xl">
                <p className="text-red-600 dark:text-red-400 text-sm text-center">
                  {video.error}
                </p>
              </div>
            )}

            {/* Tags */}
            {clipStatus?.generated_tags && (
              <div className="p-4 bg-zinc-50 dark:bg-zinc-900 rounded-xl">
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-1">
                  Generated Tags
                </p>
                <p className="text-sm text-zinc-700 dark:text-zinc-300 font-medium">
                  {clipStatus.generated_tags}
                </p>
              </div>
            )}

            {/* ── Final Video Player (as soon as video is done) ──── */}
            {videoComplete && effectiveVideoUrl && (
              <div className="w-full rounded-2xl overflow-hidden bg-black">
                <video
                  ref={videoRef}
                  src={effectiveVideoUrl}
                  controls
                  loop
                  className="w-full"
                />
              </div>
            )}

            {/* Audio player */}
            {clipStatus?.audio_url && (
              <div className="w-full">
                <audio
                  ref={audioRef}
                  controls
                  className="w-full"
                  preload="auto"
                />
              </div>
            )}

            {/* ── Download Buttons (shown as soon as video is done) ── */}
            {canDownloadVideo && (
              <div className="flex flex-col gap-3">
                {/* Combined download -- available when we have audio */}
                {canDownloadCombined && (
                  <>
                    <button
                      onClick={handleDownloadCombined}
                      disabled={isCombining}
                      className="w-full py-3 rounded-full font-medium bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:opacity-90 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                      {isCombining ? (
                        <>
                          <Spinner /> Combining...
                        </>
                      ) : (
                        <>
                          <DownloadIcon /> Download Combined Video + Audio
                        </>
                      )}
                    </button>
                    {combineError && (
                      <p className="text-xs text-red-500 text-center">
                        {combineError}
                      </p>
                    )}
                  </>
                )}

                {/* Individual downloads */}
                <div className="flex gap-3">
                  <button
                    onClick={handleDownloadVideo}
                    className="flex-1 py-2.5 rounded-full font-medium border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors flex items-center justify-center gap-2 text-sm"
                  >
                    <DownloadIcon /> Video Only
                  </button>
                  {clipStatus?.audio_url && (
                    <button
                      onClick={handleDownloadAudio}
                      className="flex-1 py-2.5 rounded-full font-medium border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors flex items-center justify-center gap-2 text-sm"
                    >
                      <DownloadIcon /> Audio Only
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <footer className="mt-auto pt-8 text-center">
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            Powered by Suno AI, HY-WorldPlay & Claude
          </p>
        </footer>
      </main>

      {/* Shimmer animation for live preview */}
      <style jsx global>{`
        @keyframes shimmer {
          0% {
            transform: translateX(-100%);
          }
          100% {
            transform: translateX(100%);
          }
        }
      `}</style>
    </div>
  );
}

// ── Small reusable components ─────────────────────────────────────

function Spinner() {
  return (
    <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
        fill="none"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg
      className="w-4 h-4"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
      />
    </svg>
  );
}
