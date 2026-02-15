"""
HY-WorldPlay on Modal

This script deploys HY-WorldPlay to Modal for GPU inference.

Usage:
    # First, set up Modal (one-time):
    pip install modal
    modal setup  # This will open a browser for authentication

    # Download models locally first, then upload to Modal volume:
    modal run modal_app.py::download_models

    # Run inference:
    modal run modal_app.py::generate --image-path /path/to/image.png --prompt "Your scene description"

    # Or deploy as a web endpoint:
    modal deploy modal_app.py

Requirements:
    - Modal account (free tier available)
    - HuggingFace token (for FLUX.1-Redux-dev access)
"""

import modal
import os
import re
import time
import json
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator

# Define the Modal app
app = modal.App("hy-worldplay")

# Create a persistent volume for storing models
model_volume = modal.Volume.from_name("hy-worldplay-models", create_if_missing=True)

# Create a volume for storing the code
code_volume = modal.Volume.from_name("hy-worldplay-code", create_if_missing=True)

# Define the container image with all dependencies
cuda_version = "12.4.0"
flavor = "devel"
os_version = "ubuntu22.04"
tag = f"{cuda_version}-{flavor}-{os_version}"

# Lightweight image for downloading models (no GPU needed)
download_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "curl", "wget")
    .pip_install(
        "huggingface-hub>=0.34.0",
        "modelscope",
        "tqdm",
    )
)

# Full GPU image for inference
image = (
    modal.Image.from_registry(f"nvidia/cuda:{tag}", add_python="3.10")
    .apt_install(
        "git",
        "ffmpeg",
        "libsm6",
        "libxext6",
        "libgl1-mesa-glx",
        "wget",
        "curl",
        "clang",
    )
    # Build tools first (rarely change)
    .pip_install(
        "wheel",
        "setuptools",
        "packaging",
        "ninja",
    )
    # Core ML frameworks - pin exact versions for flash-attn compatibility
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "torchaudio==2.5.1",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    # Flash attention - use pre-built wheel from GitHub releases
    .run_commands(
        "pip install https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.3/flash_attn-2.7.3+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"
    )
    # Other dependencies
    .pip_install(
        "tqdm==4.67.1",
        "peft==0.17.0",
        "einops==0.8.0",
        "loguru==0.7.3",
        "numpy==1.26.4",
        "pillow==11.3.0",
        "imageio==2.37.0",
        "imageio-ffmpeg==0.6.0",
        "omegaconf>=2.3.0",
        "diffusers==0.32.2",  # Use compatible diffusers version
        "safetensors>=0.5.3",
        "qwen-vl-utils==0.0.8",
        "huggingface-hub>=0.34.0",
        "transformers[accelerate,tiktoken]>=4.57.0",
        "modelscope",
        "pandas",
        "scipy",
        "protobuf",
        "moviepy==1.0.3",
        "angelslim==0.2.2",
        "sageattention",
        # FastAPI for web endpoints
        "fastapi[standard]",
    )
    .run_commands("mkdir -p /app")
)

# Model paths inside the Modal volume
MODELS_DIR = "/models"
WORLDPLAY_DIR = f"{MODELS_DIR}/HY-WorldPlay"
HUNYUAN_DIR = f"{MODELS_DIR}/HunyuanVideo-1.5"

# Secrets for HuggingFace token
hf_secret = modal.Secret.from_name("huggingface-secret", required_keys=["HF_TOKEN"])

# Code paths
CODE_DIR = "/code"


# ---------------------------------------------------------------------------
# Pydantic models for API input validation
# ---------------------------------------------------------------------------

class PosePreset(str, Enum):
    FORWARD = "w-31"
    BACKWARD = "s-31"
    LEFT = "a-31"
    RIGHT = "d-31"
    PAN_LEFT = "left-31"
    PAN_RIGHT = "right-31"
    LOOK_UP = "up-31"
    LOOK_DOWN = "down-31"


class VideoGenerateRequest(BaseModel):
    """Request body for video generation."""

    image_base64: str = Field(
        ..., description="Base64-encoded input image (PNG or JPEG)"
    )
    prompt: str = Field(
        ..., min_length=1, max_length=2000, description="Scene description"
    )
    pose: str = Field(
        default="w-31",
        description='Camera trajectory, e.g. "w-31" (forward), "s-15, right-8"',
    )
    num_frames: int = Field(
        default=125, ge=5, le=500, description="Number of video frames"
    )
    width: int = Field(default=832, ge=256, le=1920, description="Video width")
    height: int = Field(default=480, ge=256, le=1080, description="Video height")
    seed: int = Field(default=42, ge=0, description="Random seed")
    num_inference_steps: int = Field(
        default=4, ge=1, le=50, description="Diffusion denoising steps"
    )
    fps: int = Field(default=24, ge=1, le=60, description="Output FPS")

    @field_validator("image_base64")
    @classmethod
    def validate_base64(cls, v):
        import base64 as b64

        try:
            data = b64.b64decode(v)
            if len(data) < 100:
                raise ValueError("Image data too small")
            if len(data) > 50 * 1024 * 1024:
                raise ValueError("Image data too large (>50MB)")
        except Exception as e:
            raise ValueError(f"Invalid base64 image: {e}")
        return v

    @field_validator("num_frames")
    @classmethod
    def validate_frames(cls, v):
        if ((v - 1) // 4 + 1) % 4 != 0:
            raise ValueError(
                f"num_frames={v} invalid: ((num_frames - 1) // 4 + 1) must be "
                f"divisible by 4. Valid examples: 13, 29, 45, 61, 77, 93, 109, 125"
            )
        return v


# ---------------------------------------------------------------------------
# Torchrun progress parser — turns raw stdout into structured SSE events
# ---------------------------------------------------------------------------

class TorchrunProgressParser:
    """Parse torchrun stdout to extract progress events for SSE streaming."""

    TQDM_RE = re.compile(r"(\d+)%\|.*?\|\s*(\d+)/(\d+)")
    TASK_BANNER_RE = re.compile(r"HunyuanVideo Generation Task")
    MODEL_LOAD_RE = re.compile(r"HY-World 1\.5 loading from:")
    VIDEO_SAVED_RE = re.compile(r"Saved video to:")

    def __init__(self, num_inference_steps: int = 4, num_frames: int = 125):
        self.steps_per_chunk = num_inference_steps
        latent_frames = (num_frames - 1) // 4 + 1
        self.total_chunks = max(latent_frames // 4, 1)
        self._chunks_completed = 0
        self.status = "starting"

    def parse_line(self, line: str) -> list[dict]:
        """Return a list of ``{"event": ..., "data": {...}}`` dicts."""
        events: list[dict] = []

        if self.MODEL_LOAD_RE.search(line):
            self.status = "loading"
            events.append(
                {"event": "status", "data": {"status": "loading", "message": "Loading model weights..."}}
            )

        if self.TASK_BANNER_RE.search(line):
            self.status = "generating"
            events.append(
                {"event": "status", "data": {"status": "generating", "message": "Starting video generation..."}}
            )

        m = self.TQDM_RE.search(line)
        if m:
            pct_local = int(m.group(1))
            step = int(m.group(2))
            total = int(m.group(3))

            if pct_local == 100 or step == total:
                self._chunks_completed += 1

            overall = self._overall_pct(step, total)
            events.append(
                {
                    "event": "progress",
                    "data": {
                        "step": step,
                        "total_steps": total,
                        "chunk": min(self._chunks_completed, self.total_chunks),
                        "total_chunks": self.total_chunks,
                        "percentage": overall,
                    },
                }
            )

        if self.VIDEO_SAVED_RE.search(line):
            self.status = "encoding"
            events.append(
                {"event": "status", "data": {"status": "encoding", "message": "Encoding video output..."}}
            )

        return events

    def _overall_pct(self, step: int, total: int) -> float:
        chunk_frac = step / max(total, 1)
        completed = max(0, self._chunks_completed - (1 if step == total else 0))
        pct = (completed + chunk_frac) / max(self.total_chunks, 1) * 100
        return min(round(pct, 1), 100.0)


@app.function(
    image=image,
    volumes={CODE_DIR: code_volume},
    timeout=600,
)
def upload_code():
    """
    Upload local code to Modal volume.

    Run this before inference to sync your code:
        modal run modal_app.py::upload_code
    """
    import shutil
    import subprocess

    print("Uploading code to Modal volume...")

    # The code is passed via modal's local file mounting during function call
    # We need to clone from git or upload manually

    # For now, clone from the repo
    repo_url = "https://github.com/Tencent/HunyuanVideo"  # Update if different

    # Alternative: Use modal volume put command locally before running
    print("Code upload complete. Use 'modal volume put' to upload your local code:")
    print(f"  modal volume put hy-worldplay-code ./hyvideo /hyvideo")
    print(f"  modal volume put hy-worldplay-code ./trainer /trainer")
    print(f"  modal volume put hy-worldplay-code ./wan /wan")

    code_volume.commit()
    return {"status": "instructions_printed"}


@app.local_entrypoint()
def sync_code():
    """
    Sync local code to Modal volume using modal volume commands.

    Usage:
        modal run modal_app.py::sync_code
    """
    import subprocess
    import sys

    print("Syncing code to Modal volume...")

    dirs_to_sync = ["hyvideo", "trainer", "wan"]

    for dir_name in dirs_to_sync:
        if os.path.isdir(dir_name):
            print(f"Uploading {dir_name}...")
            result = subprocess.run(
                ["modal", "volume", "put", "--force", "hy-worldplay-code", f"./{dir_name}", f"/{dir_name}"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"Error uploading {dir_name}: {result.stderr}")
            else:
                print(f"✅ Uploaded {dir_name}")

    print("✅ Code sync complete!")


@app.function(
    image=download_image,
    secrets=[hf_secret],
    volumes={MODELS_DIR: model_volume},
    timeout=600,
)
def download_vision_encoder():
    """
    Download just the vision encoder (SigLIP from FLUX.1-Redux-dev).

    Run this if the vision encoder was not downloaded:
        modal run modal_app.py::download_vision_encoder

    Requires:
        1. Access to https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev
        2. HuggingFace secret: modal secret create huggingface-secret HF_TOKEN=<your_token>
    """
    import shutil
    from huggingface_hub import snapshot_download

    hf_token = os.environ.get("HF_TOKEN", "")

    if not hf_token:
        print("ERROR: No HF_TOKEN found!")
        print("Please run: modal secret create huggingface-secret HF_TOKEN=<your_token>")
        return {"status": "error", "message": "No HF_TOKEN"}

    print("Downloading Vision Encoder (SigLIP from FLUX.1-Redux-dev)...")

    vision_dir = os.path.join(HUNYUAN_DIR, "vision_encoder")
    os.makedirs(vision_dir, exist_ok=True)
    sigclip_dst = os.path.join(vision_dir, "siglip")

    try:
        flux_cache = snapshot_download(
            "black-forest-labs/FLUX.1-Redux-dev",
            allow_patterns=["image_encoder/*", "feature_extractor/*"],
            token=hf_token,
        )
        if os.path.exists(sigclip_dst):
            shutil.rmtree(sigclip_dst)
        os.makedirs(sigclip_dst, exist_ok=True)
        for item in os.listdir(flux_cache):
            src = os.path.realpath(os.path.join(flux_cache, item))
            dst = os.path.join(sigclip_dst, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        print(f"✅ Downloaded to: {sigclip_dst}")

        model_volume.commit()
        return {"status": "success", "path": sigclip_dst}
    except Exception as e:
        print(f"ERROR: Could not download vision encoder: {e}")
        print("\nTo fix this:")
        print("1. Go to: https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev")
        print("2. Click 'Agree and access repository' to accept the license")
        print("3. Make sure your HF token has read access")
        print("4. Re-run: modal run modal_app.py::download_vision_encoder")
        return {"status": "error", "message": str(e)}


@app.function(
    image=download_image,
    secrets=[hf_secret],
    volumes={MODELS_DIR: model_volume},
    timeout=3600,  # 1 hour timeout for downloading
    cpu=4,
)
def download_models():
    """
    Download all required models to the Modal volume.

    Run this once before inference:
        modal run modal_app.py::download_models

    Make sure you have set up the HuggingFace secret:
        modal secret create huggingface-secret HF_TOKEN=<your_token>
    """
    import shutil
    from huggingface_hub import snapshot_download

    os.environ["HF_TOKEN"] = os.environ.get("HF_TOKEN", "")
    hf_token = os.environ["HF_TOKEN"]

    print("=" * 60)
    print("Downloading HY-WorldPlay models to Modal volume...")
    print("=" * 60)

    # 1. Download HY-WorldPlay
    print("\n[1/6] Downloading tencent/HY-WorldPlay...")
    worldplay_cache = snapshot_download("tencent/HY-WorldPlay")

    # Copy to volume
    if os.path.exists(WORLDPLAY_DIR):
        shutil.rmtree(WORLDPLAY_DIR)
    shutil.copytree(worldplay_cache, WORLDPLAY_DIR, dirs_exist_ok=True)

    # Fix: Rename model.safetensors to diffusion_pytorch_model.safetensors
    ar_distill_dir = os.path.join(WORLDPLAY_DIR, "ar_distilled_action_model")
    model_src = os.path.join(ar_distill_dir, "model.safetensors")
    model_dst = os.path.join(ar_distill_dir, "diffusion_pytorch_model.safetensors")
    if os.path.exists(model_src) and not os.path.exists(model_dst):
        shutil.copy2(model_src, model_dst)
        print("Fixed: Renamed model.safetensors -> diffusion_pytorch_model.safetensors")

    print(f"Downloaded to: {WORLDPLAY_DIR}")

    # 2. Download HunyuanVideo-1.5 (vae, scheduler, transformer)
    print("\n[2/6] Downloading tencent/HunyuanVideo-1.5...")
    hunyuan_cache = snapshot_download(
        "tencent/HunyuanVideo-1.5",
        allow_patterns=["vae/*", "scheduler/*", "transformer/480p_i2v/*"],
    )

    if os.path.exists(HUNYUAN_DIR):
        shutil.rmtree(HUNYUAN_DIR)
    shutil.copytree(hunyuan_cache, HUNYUAN_DIR, dirs_exist_ok=True)
    print(f"Downloaded to: {HUNYUAN_DIR}")

    # 3. Download LLM text encoder (Qwen2.5-VL-7B-Instruct)
    print("\n[3/6] Downloading Qwen/Qwen2.5-VL-7B-Instruct...")
    text_encoder_base = os.path.join(HUNYUAN_DIR, "text_encoder")
    os.makedirs(text_encoder_base, exist_ok=True)
    llm_target = os.path.join(text_encoder_base, "llm")

    qwen_cache = snapshot_download("Qwen/Qwen2.5-VL-7B-Instruct")
    if os.path.exists(llm_target):
        shutil.rmtree(llm_target)
    os.makedirs(llm_target, exist_ok=True)
    for item in os.listdir(qwen_cache):
        src = os.path.realpath(os.path.join(qwen_cache, item))
        dst = os.path.join(llm_target, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    print(f"Downloaded to: {llm_target}")

    # 4. Download ByT5 encoders
    print("\n[4/6] Downloading ByT5 encoders...")
    from modelscope import snapshot_download as ms_snapshot_download

    byt5_target = os.path.join(text_encoder_base, "byt5-small")
    byt5_cache = snapshot_download("google/byt5-small")
    if os.path.exists(byt5_target):
        shutil.rmtree(byt5_target)
    os.makedirs(byt5_target, exist_ok=True)
    for item in os.listdir(byt5_cache):
        src = os.path.realpath(os.path.join(byt5_cache, item))
        dst = os.path.join(byt5_target, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    print(f"Downloaded byt5-small to: {byt5_target}")

    glyph_target = os.path.join(text_encoder_base, "Glyph-SDXL-v2")
    glyph_cache = ms_snapshot_download("AI-ModelScope/Glyph-SDXL-v2", cache_dir="/tmp/glyph_cache")
    if os.path.exists(glyph_target):
        shutil.rmtree(glyph_target)
    shutil.copytree(glyph_cache, glyph_target, dirs_exist_ok=True)
    print(f"Downloaded Glyph-SDXL-v2 to: {glyph_target}")

    # 5. Download Vision Encoder (FLUX.1-Redux-dev)
    print("\n[5/6] Downloading Vision Encoder (SigLIP)...")
    vision_dir = os.path.join(HUNYUAN_DIR, "vision_encoder")
    os.makedirs(vision_dir, exist_ok=True)
    sigclip_dst = os.path.join(vision_dir, "siglip")

    if hf_token:
        try:
            flux_cache = snapshot_download(
                "black-forest-labs/FLUX.1-Redux-dev",
                allow_patterns=["image_encoder/*", "feature_extractor/*"],
                token=hf_token,
            )
            if os.path.exists(sigclip_dst):
                shutil.rmtree(sigclip_dst)
            os.makedirs(sigclip_dst, exist_ok=True)
            for item in os.listdir(flux_cache):
                src = os.path.realpath(os.path.join(flux_cache, item))
                dst = os.path.join(sigclip_dst, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
            print(f"Downloaded to: {sigclip_dst}")
        except Exception as e:
            print(f"WARNING: Could not download vision encoder: {e}")
            print("Make sure you have access to FLUX.1-Redux-dev on HuggingFace")
            print("1. Go to: https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev")
            print("2. Accept the license agreement")
            print("3. Make sure your HF_TOKEN has read access")
    else:
        print("WARNING: No HF_TOKEN provided!")
        print("Vision encoder requires access to a gated model.")
        print("To fix this:")
        print("1. Get access to: https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev")
        print("2. Create a token at: https://huggingface.co/settings/tokens")
        print("3. Run: modal secret create huggingface-secret HF_TOKEN=<your_token>")
        print("4. Re-run this download function")

    # Commit the volume
    model_volume.commit()

    print("\n" + "=" * 60)
    print("✅ All models downloaded successfully!")
    print("=" * 60)
    print(f"\nModel paths:")
    print(f"  MODEL_PATH: {HUNYUAN_DIR}")
    print(f"  AR_ACTION_MODEL_PATH: {WORLDPLAY_DIR}/ar_model")
    print(f"  BI_ACTION_MODEL_PATH: {WORLDPLAY_DIR}/bidirectional_model")
    print(f"  AR_DISTILL_ACTION_MODEL_PATH: {WORLDPLAY_DIR}/ar_distilled_action_model")

    return {"status": "success", "model_path": HUNYUAN_DIR, "worldplay_path": WORLDPLAY_DIR}


N_GPUS = 4  # Number of GPUs for sequence-parallel inference (must divide attention head count: 1, 2, 4, or 8)


# ---------------------------------------------------------------------------
# Shared helpers — used by both CLI and API paths
# ---------------------------------------------------------------------------

def _build_torchrun_command(
    image_path: str,
    output_dir: str,
    prompt: str,
    pose: str = "w-31",
    num_frames: int = 125,
    width: int = 832,
    height: int = 480,
    seed: int = 42,
    num_inference_steps: int = 4,
    fps: int = 24,
) -> list:
    """Build the torchrun command list for video generation."""
    action_ckpt = f"{WORLDPLAY_DIR}/ar_distilled_action_model/diffusion_pytorch_model.safetensors"
    return [
        "torchrun",
        f"--nproc_per_node={N_GPUS}",
        f"{CODE_DIR}/hyvideo/generate.py",
        "--prompt", prompt,
        "--image_path", image_path,
        "--resolution", "480p",
        "--aspect_ratio", "16:9",
        "--video_length", str(num_frames),
        "--seed", str(seed),
        "--rewrite", "false",
        "--sr", "false",
        "--pose", pose,
        "--output_path", output_dir,
        "--model_path", HUNYUAN_DIR,
        "--action_ckpt", action_ckpt,
        "--few_step", "true",
        "--num_inference_steps", str(num_inference_steps),
        "--model_type", "ar",
        "--offloading", "false",
        "--group_offloading", "false",
        "--use_vae_parallel", "false",
        "--use_sageattn", "false",
        "--use_fp8_gemm", "false",
        "--enable_torch_compile", "false",
        "--fps", str(fps),
        "--width", str(width),
        "--height", str(height),
    ]


def _get_torchrun_env() -> dict:
    """Get environment variables for torchrun."""
    env = os.environ.copy()
    env["PYTHONPATH"] = CODE_DIR + ":" + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


@app.cls(
    image=image,
    gpu=f"H200:{N_GPUS}",
    volumes={MODELS_DIR: model_volume, CODE_DIR: code_volume},
    timeout=1800,  # 30 minute timeout
    scaledown_window=300,  # Keep warm for 5 minutes
)
class WorldPlayInference:
    """
    WorldPlay inference class for Modal.

    Uses torchrun to launch 8 GPU processes with sequence parallelism,
    matching the official run.sh approach.
    """

    @modal.enter()
    def setup(self):
        """Verify model files exist when container starts."""
        action_ckpt = f"{WORLDPLAY_DIR}/ar_distilled_action_model/diffusion_pytorch_model.safetensors"
        required = [
            f"{HUNYUAN_DIR}/transformer/480p_i2v",
            f"{HUNYUAN_DIR}/vae",
            f"{HUNYUAN_DIR}/scheduler",
            f"{HUNYUAN_DIR}/text_encoder/llm",
            f"{HUNYUAN_DIR}/vision_encoder/siglip",
            action_ckpt,
        ]
        missing = [p for p in required if not os.path.exists(p)]
        if missing:
            raise FileNotFoundError(
                f"Missing model files: {missing}. Run 'modal run modal_app.py::download_models' first."
            )
        print(f"✅ All model files verified. Ready for {N_GPUS}-GPU inference.")

    @modal.method()
    def generate(
        self,
        image_bytes: bytes,
        prompt: str,
        pose: str = "w-31",
        num_frames: int = 125,
        width: int = 832,
        height: int = 480,
        seed: int = 42,
        num_inference_steps: int = 4,
        fps: int = 24,
    ) -> bytes:
        """
        Generate a video from an image and prompt using 8-GPU torchrun.

        Args:
            image_bytes: Input image as bytes
            prompt: Text description of the scene
            pose: Camera trajectory (e.g., "w-31" for forward movement)
            num_frames: Number of frames to generate (default: 125)
            width: Video width (default: 832)
            height: Video height (default: 480)
            seed: Random seed
            num_inference_steps: Number of diffusion steps (default: 4 for distilled model)

        Returns:
            Generated video as MP4 bytes
        """
        import subprocess
        import tempfile
        from PIL import Image
        import io

        # Save input image to temp file
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = image.resize((width, height))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            image_path = f.name
            image.save(image_path)

        output_dir = tempfile.mkdtemp(prefix="modal_output_")

        print(f"Generating video: {num_frames} frames, {width}x{height}, {N_GPUS} GPUs")
        print(f"Prompt: {prompt}")
        print(f"Pose: {pose}")

        cmd = _build_torchrun_command(
            image_path=image_path,
            output_dir=output_dir,
            prompt=prompt,
            pose=pose,
            num_frames=num_frames,
            width=width,
            height=height,
            seed=seed,
            num_inference_steps=num_inference_steps,
            fps=fps,
        )
        env = _get_torchrun_env()

        import sys

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=env,
        )

        import os as _os
        while True:
            chunk = _os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()

        proc.wait()

        os.unlink(image_path)

        if proc.returncode != 0:
            raise RuntimeError(
                f"torchrun failed with return code {proc.returncode}"
            )

        video_path = os.path.join(output_dir, "gen.mp4")
        if not os.path.exists(video_path):
            raise FileNotFoundError(
                f"Expected output at {video_path} but not found. "
                f"Contents of {output_dir}: {os.listdir(output_dir)}"
            )

        with open(video_path, "rb") as f:
            video_bytes = f.read()

        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)

        print(f"✅ Video generated: {len(video_bytes)} bytes")
        return video_bytes


@app.local_entrypoint()
def generate(
    image_path: str = "./assets/img/test.png",
    prompt: str = "A paved pathway leads towards a stone arch bridge spanning a calm body of water.",
    pose: str = "w-31",
    num_frames: int = 125,
    seed: int = 42,
    fps: int = 24,
    output_path: str = "./outputs/modal_output.mp4",
):
    """
    Generate a video using HY-WorldPlay on Modal.

    Usage:
        modal run modal_app.py::generate --image-path /path/to/image.png --prompt "Your description"
    """
    import os

    # Read the input image
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    print(f"Input image: {image_path}")
    print(f"Prompt: {prompt}")
    print(f"Pose: {pose}")

    # Create inference instance and generate
    inference = WorldPlayInference()
    video_bytes = inference.generate.remote(
        image_bytes=image_bytes,
        prompt=prompt,
        pose=pose,
        num_frames=num_frames,
        seed=seed,
        fps=fps,
    )

    # Save output video
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(video_bytes)

    print(f"✅ Video saved to: {output_path}")


# DEPRECATED: Use WorldPlayAPI instead (supports SSE streaming, CORS, proper validation).
# Kept for backward compatibility with existing deployments.
@app.function(
    image=image,
    gpu=f"H200:{N_GPUS}",
    volumes={MODELS_DIR: model_volume, CODE_DIR: code_volume},
    timeout=1800,
    scaledown_window=300,
)
@modal.fastapi_endpoint(method="POST")
def generate_video_api(request: dict):
    """
    DEPRECATED: Use the WorldPlayAPI class endpoints instead.

    Web API endpoint for video generation using 8-GPU torchrun.

    Deploy with: modal deploy modal_app.py

    Request body (JSON):
    {
        "image_base64": "<base64 encoded image>",
        "prompt": "Scene description",
        "pose": "w-31",
        "num_frames": 125,
        "seed": 42
    }

    Returns:
    {
        "video_base64": "<base64 encoded MP4 video>"
    }
    """
    import base64
    import subprocess
    import sys
    import shutil
    import tempfile
    from PIL import Image
    import io

    # Decode image
    image_base64 = request.get("image_base64", "")
    image_bytes = base64.b64decode(image_base64)

    prompt = request.get("prompt", "A beautiful landscape scene.")
    pose = request.get("pose", "w-31")
    num_frames = request.get("num_frames", 125)
    seed = request.get("seed", 42)
    width = request.get("width", 832)
    height = request.get("height", 480)
    num_inference_steps = request.get("num_inference_steps", 4)
    fps = request.get("fps", 24)

    # Save input image to temp file
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image = image.resize((width, height))

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        image_path = f.name
        image.save(image_path)

    output_dir = tempfile.mkdtemp(prefix="modal_api_output_")
    action_ckpt = f"{WORLDPLAY_DIR}/ar_distilled_action_model/diffusion_pytorch_model.safetensors"

    cmd = [
        "torchrun",
        f"--nproc_per_node={N_GPUS}",
        f"{CODE_DIR}/hyvideo/generate.py",
        "--prompt", prompt,
        "--image_path", image_path,
        "--resolution", "480p",
        "--aspect_ratio", "16:9",
        "--video_length", str(num_frames),
        "--seed", str(seed),
        "--rewrite", "false",
        "--sr", "false",
        "--pose", pose,
        "--output_path", output_dir,
        "--model_path", HUNYUAN_DIR,
        "--action_ckpt", action_ckpt,
        "--few_step", "true",
        "--num_inference_steps", str(num_inference_steps),
        "--model_type", "ar",
        "--offloading", "false",
        "--group_offloading", "false",
        "--use_vae_parallel", "false",
        "--use_sageattn", "false",
        "--use_fp8_gemm", "false",
        "--enable_torch_compile", "false",
        "--fps", str(fps),
        "--width", str(width),
        "--height", str(height),
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = CODE_DIR + ":" + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=env,
    )

    import os as _os
    while True:
        chunk = _os.read(proc.stdout.fileno(), 4096)
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()

    proc.wait()

    os.unlink(image_path)

    if proc.returncode != 0:
        raise RuntimeError(
            f"torchrun failed with return code {proc.returncode}"
        )

    video_path = os.path.join(output_dir, "gen.mp4")
    if not os.path.exists(video_path):
        raise FileNotFoundError(
            f"Expected output at {video_path} but not found. "
            f"Contents of {output_dir}: {os.listdir(output_dir)}"
        )

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    shutil.rmtree(output_dir, ignore_errors=True)

    video_base64 = base64.b64encode(video_bytes).decode("utf-8")
    return {"video_base64": video_base64}


# ---------------------------------------------------------------------------
# WorldPlayAPI — SSE streaming, CORS, proper validation, designed for Next.js
# ---------------------------------------------------------------------------

_REQUIRED_MODEL_PATHS = [
    f"{HUNYUAN_DIR}/transformer/480p_i2v",
    f"{HUNYUAN_DIR}/vae",
    f"{HUNYUAN_DIR}/scheduler",
    f"{HUNYUAN_DIR}/text_encoder/llm",
    f"{HUNYUAN_DIR}/vision_encoder/siglip",
    f"{WORLDPLAY_DIR}/ar_distilled_action_model/diffusion_pytorch_model.safetensors",
]


@app.cls(
    image=image,
    gpu=f"H200:{N_GPUS}",
    volumes={MODELS_DIR: model_volume, CODE_DIR: code_volume},
    timeout=1800,
    scaledown_window=300,
)
class WorldPlayAPI:
    """Full FastAPI app with SSE streaming for real-time video generation."""

    @modal.enter()
    def setup(self):
        missing = [p for p in _REQUIRED_MODEL_PATHS if not os.path.exists(p)]
        if missing:
            raise FileNotFoundError(
                f"Missing model files: {missing}. "
                "Run 'modal run modal_app.py::download_models' first."
            )
        self._video_store: dict[str, bytes] = {}
        print(f"All model files verified. WorldPlayAPI ready ({N_GPUS} GPUs).")

    @modal.asgi_app()
    def web(self):
        import asyncio
        import base64
        import subprocess
        import tempfile
        import threading
        import uuid
        import shutil
        from io import BytesIO

        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse, Response
        from PIL import Image

        api = FastAPI(
            title="HY-WorldPlay API",
            description="Video generation with SSE streaming",
            version="1.0.0",
        )
        api.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        store = self._video_store  # closure ref

        # ── helpers ───────────────────────────────────────────────

        def _prepare_image(request: VideoGenerateRequest) -> tuple[str, str]:
            """Decode image, save to temp file. Returns (image_path, output_dir)."""
            raw = base64.b64decode(request.image_base64)
            img = Image.open(BytesIO(raw)).convert("RGB").resize(
                (request.width, request.height)
            )
            f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            img.save(f.name)
            f.close()
            out_dir = tempfile.mkdtemp(prefix="modal_sse_")
            return f.name, out_dir

        def _read_video(output_dir: str) -> bytes:
            video_path = os.path.join(output_dir, "gen.mp4")
            if not os.path.exists(video_path):
                raise FileNotFoundError(
                    f"Expected output at {video_path}. "
                    f"Dir contents: {os.listdir(output_dir)}"
                )
            with open(video_path, "rb") as f:
                return f.read()

        # ── routes ────────────────────────────────────────────────

        @api.get("/health")
        async def health():
            return {"status": "ok", "gpus": N_GPUS, "model": "HY-WorldPlay"}

        @api.get("/config")
        async def config():
            return {
                "pose_presets": {p.name: p.value for p in PosePreset},
                "defaults": {
                    "num_frames": 125,
                    "width": 832,
                    "height": 480,
                    "num_inference_steps": 4,
                    "fps": 24,
                    "seed": 42,
                    "pose": "w-31",
                },
                "limits": {
                    "max_image_size_mb": 50,
                    "max_prompt_length": 2000,
                    "max_num_frames": 500,
                },
            }

        @api.post("/generate")
        async def generate_sse(request: VideoGenerateRequest):
            """
            Stream generation progress via SSE, then deliver the video.

            **Event types:**
            - `status`   — `{status, message, job_id?}`
            - `progress` — `{step, total_steps, chunk, total_chunks, percentage}`
            - `complete` — `{video_base64, job_id, download_url, size_bytes}`
            - `error`    — `{error, details?}`
            """
            job_id = uuid.uuid4().hex

            async def event_stream():
                image_path = output_dir = None
                try:
                    yield _sse("status", {
                        "status": "starting",
                        "message": "Preparing generation...",
                        "job_id": job_id,
                    })

                    image_path, output_dir = _prepare_image(request)

                    cmd = _build_torchrun_command(
                        image_path=image_path,
                        output_dir=output_dir,
                        prompt=request.prompt,
                        pose=request.pose,
                        num_frames=request.num_frames,
                        width=request.width,
                        height=request.height,
                        seed=request.seed,
                        num_inference_steps=request.num_inference_steps,
                        fps=request.fps,
                    )
                    env = _get_torchrun_env()
                    parser = TorchrunProgressParser(
                        num_inference_steps=request.num_inference_steps,
                        num_frames=request.num_frames,
                    )

                    yield _sse("status", {
                        "status": "loading",
                        "message": "Launching torchrun...",
                    })

                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        bufsize=0,
                        env=env,
                    )

                    # Bridge blocking subprocess I/O → async via thread + queue
                    queue: asyncio.Queue[str | None] = asyncio.Queue()
                    loop = asyncio.get_event_loop()

                    def _reader():
                        buf = b""
                        while True:
                            chunk = os.read(proc.stdout.fileno(), 4096)
                            if not chunk:
                                if buf:
                                    loop.call_soon_threadsafe(
                                        queue.put_nowait,
                                        buf.decode("utf-8", errors="replace"),
                                    )
                                loop.call_soon_threadsafe(queue.put_nowait, None)
                                break
                            buf += chunk
                            while b"\n" in buf or b"\r" in buf:
                                idx_n = buf.find(b"\n")
                                idx_r = buf.find(b"\r")
                                if idx_n == -1:
                                    idx_n = len(buf)
                                if idx_r == -1:
                                    idx_r = len(buf)
                                idx = min(idx_n, idx_r)
                                line = buf[:idx].decode("utf-8", errors="replace")
                                buf = buf[idx + 1 :]
                                if line.strip():
                                    loop.call_soon_threadsafe(
                                        queue.put_nowait, line
                                    )

                    threading.Thread(target=_reader, daemon=True).start()

                    # Consume lines and emit SSE events
                    while True:
                        try:
                            line = await asyncio.wait_for(queue.get(), timeout=120)
                        except asyncio.TimeoutError:
                            yield ": keepalive\n\n"
                            continue
                        if line is None:
                            break
                        for ev in parser.parse_line(line):
                            yield _sse(ev["event"], ev["data"])

                    proc.wait()

                    if image_path and os.path.exists(image_path):
                        os.unlink(image_path)

                    if proc.returncode != 0:
                        yield _sse("error", {
                            "error": "Generation failed",
                            "details": f"torchrun exit code {proc.returncode}",
                        })
                        return

                    video_bytes = _read_video(output_dir)
                    shutil.rmtree(output_dir, ignore_errors=True)
                    output_dir = None

                    # Store for /download endpoint (auto-expire 10 min)
                    store[job_id] = video_bytes

                    async def _expire():
                        await asyncio.sleep(600)
                        store.pop(job_id, None)

                    asyncio.ensure_future(_expire())

                    vid_b64 = base64.b64encode(video_bytes).decode("utf-8")
                    yield _sse("status", {
                        "status": "complete",
                        "message": "Video generation complete",
                    })
                    yield _sse("complete", {
                        "video_base64": vid_b64,
                        "job_id": job_id,
                        "download_url": f"/download/{job_id}",
                        "size_bytes": len(video_bytes),
                    })

                except Exception as exc:
                    yield _sse("error", {
                        "error": str(exc),
                        "details": type(exc).__name__,
                    })
                finally:
                    if image_path and os.path.exists(image_path):
                        os.unlink(image_path)
                    if output_dir and os.path.exists(output_dir):
                        shutil.rmtree(output_dir, ignore_errors=True)

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Job-ID": job_id,
                },
            )

        @api.post("/generate/sync")
        async def generate_sync(request: VideoGenerateRequest):
            """Blocking endpoint — returns JSON with video_base64 (no streaming)."""
            image_path, output_dir = _prepare_image(request)
            try:
                cmd = _build_torchrun_command(
                    image_path=image_path,
                    output_dir=output_dir,
                    prompt=request.prompt,
                    pose=request.pose,
                    num_frames=request.num_frames,
                    width=request.width,
                    height=request.height,
                    seed=request.seed,
                    num_inference_steps=request.num_inference_steps,
                    fps=request.fps,
                )
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                    env=_get_torchrun_env(),
                )
                import sys
                while True:
                    chunk = os.read(proc.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()

                proc.wait()
                if proc.returncode != 0:
                    raise HTTPException(
                        status_code=500,
                        detail=f"torchrun failed (exit code {proc.returncode})",
                    )
                video_bytes = _read_video(output_dir)
                return {
                    "video_base64": base64.b64encode(video_bytes).decode("utf-8"),
                    "size_bytes": len(video_bytes),
                }
            finally:
                if os.path.exists(image_path):
                    os.unlink(image_path)
                shutil.rmtree(output_dir, ignore_errors=True)

        @api.get("/download/{job_id}")
        async def download_video(job_id: str):
            """Download a generated video by job ID (available for 10 minutes)."""
            if job_id not in store:
                raise HTTPException(
                    status_code=404, detail="Video not found or expired"
                )
            video_bytes = store.pop(job_id)
            return Response(
                content=video_bytes,
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="worldplay_{job_id}.mp4"'
                },
            )

        return api


def _sse(event: str, data: dict) -> str:
    """Format a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

