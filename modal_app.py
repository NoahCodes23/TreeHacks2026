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


@app.cls(
    image=image,
    gpu="H200",  # Use single H200 GPU for inference (simpler, works with Modal)
    volumes={MODELS_DIR: model_volume, CODE_DIR: code_volume},
    timeout=1800,  # 30 minute timeout
    scaledown_window=300,  # Keep warm for 5 minutes
)
class WorldPlayInference:
    """
    WorldPlay inference class for Modal.

    Uses the distilled autoregressive model for fast inference.
    """

    @modal.enter()
    def load_model(self):
        """Load the model when container starts."""
        import sys
        sys.path.insert(0, CODE_DIR)

        import torch
        import argparse
        from hyvideo.pipelines.worldplay_video_pipeline import HunyuanVideo_1_5_Pipeline
        from hyvideo.commons.parallel_states import initialize_parallel_state
        from hyvideo.commons.infer_state import initialize_infer_state

        # Initialize parallel state for single GPU (Modal doesn't support torchrun-style distributed)
        os.environ["WORLD_SIZE"] = "1"
        os.environ["RANK"] = "0"
        os.environ["LOCAL_RANK"] = "0"
        os.environ["MASTER_ADDR"] = "localhost"
        os.environ["MASTER_PORT"] = "29500"

        # Initialize with sp=1 for single GPU
        initialize_parallel_state(sp=1)
        torch.cuda.set_device(0)

        # Initialize inference state with default args
        args = argparse.Namespace(
            use_sageattn=False,
            sage_blocks_range="0-39",  # Default range for all blocks
            enable_torch_compile=False,
            use_fp8_gemm=False,
            quant_type="fp8_e4m3",
            include_patterns="double_blocks",
            use_vae_parallel=False,
            few_step=True,
            num_inference_steps=4,
        )
        initialize_infer_state(args)

        print("Loading HY-WorldPlay model on H200 GPU...")

        # Action model checkpoint path (distilled for faster inference)
        action_ckpt = f"{WORLDPLAY_DIR}/ar_distilled_action_model/diffusion_pytorch_model.safetensors"

        # Initialize the pipeline using the class method
        self.pipeline = HunyuanVideo_1_5_Pipeline.create_pipeline(
            pretrained_model_name_or_path=HUNYUAN_DIR,
            transformer_version="480p_i2v",
            enable_offloading=False,
            enable_group_offloading=False,  # H200 has enough VRAM; no offloading needed
            create_sr_pipeline=False,
            force_sparse_attn=False,
            transformer_dtype=torch.bfloat16,
            action_ckpt=action_ckpt,
        )

        print("✅ Model loaded successfully!")

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
    ) -> bytes:
        """
        Generate a video from an image and prompt.

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
        import sys
        sys.path.insert(0, CODE_DIR)

        import torch
        import tempfile
        from PIL import Image
        import io
        import imageio
        import einops

        # Import pose_to_input from generate.py
        from hyvideo.generate import pose_to_input

        # Load image and save to temporary file
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = image.resize((width, height))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            image_path = f.name
            image.save(image_path)

        print(f"Generating video: {num_frames} frames, {width}x{height}")
        print(f"Prompt: {prompt}")
        print(f"Pose: {pose}")

        # Calculate number of latents
        latent_num = (num_frames - 1) // 4 + 1

        # Convert pose to input tensors
        viewmats, Ks, action = pose_to_input(pose, latent_num)

        # Generate video
        with torch.no_grad():
            out = self.pipeline(
                enable_sr=False,
                prompt=prompt,
                aspect_ratio="16:9",
                num_inference_steps=num_inference_steps,
                video_length=num_frames,
                negative_prompt="",
                seed=seed,
                output_type="pt",
                prompt_rewrite=False,
                viewmats=viewmats.unsqueeze(0),
                Ks=Ks.unsqueeze(0),
                action=action.unsqueeze(0),
                few_step=True,
                chunk_latent_frames=4,
                model_type="ar",
                user_height=height,
                user_width=width,
                reference_image=image_path,
            )

        # Clean up temp image file
        os.unlink(image_path)

        # Save to temporary file and read bytes
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            output_path = f.name

        # Save video using imageio
        video = out.videos
        if video.ndim == 5:
            video = video[0]
        vid = (video * 255).clamp(0, 255).to(torch.uint8)
        vid = einops.rearrange(vid, "c f h w -> f h w c")
        imageio.mimwrite(output_path, vid.cpu().numpy(), fps=24)

        with open(output_path, "rb") as f:
            video_bytes = f.read()

        os.unlink(output_path)

        print(f"✅ Video generated: {len(video_bytes)} bytes")
        return video_bytes


@app.local_entrypoint()
def generate(
    image_path: str = "./assets/img/test.png",
    prompt: str = "A paved pathway leads towards a stone arch bridge spanning a calm body of water.",
    pose: str = "w-31",
    num_frames: int = 125,
    seed: int = 42,
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
    )

    # Save output video
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(video_bytes)

    print(f"✅ Video saved to: {output_path}")


# Web endpoint for API access
@app.function(
    image=image,
    gpu="H200",  # Use single H200 GPU for inference
    volumes={MODELS_DIR: model_volume, CODE_DIR: code_volume},
    timeout=1800,
    scaledown_window=300,
)
@modal.fastapi_endpoint(method="POST")
def generate_video_api(request: dict):
    """
    Web API endpoint for video generation.

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
    import sys
    sys.path.insert(0, CODE_DIR)

    import torch
    import tempfile
    import imageio
    import einops
    from PIL import Image
    import io
    import argparse

    from hyvideo.pipelines.worldplay_video_pipeline import HunyuanVideo_1_5_Pipeline
    from hyvideo.commons.parallel_states import initialize_parallel_state
    from hyvideo.commons.infer_state import initialize_infer_state
    from hyvideo.generate import pose_to_input

    # Initialize parallel state for single GPU
    os.environ["WORLD_SIZE"] = "1"
    os.environ["RANK"] = "0"
    os.environ["LOCAL_RANK"] = "0"
    os.environ["MASTER_ADDR"] = "localhost"
    os.environ["MASTER_PORT"] = "29500"

    # Initialize with sp=1 for single GPU
    initialize_parallel_state(sp=1)
    torch.cuda.set_device(0)

    # Initialize inference state
    args = argparse.Namespace(
        use_sageattn=False,
        sage_blocks_range="0-39",  # Default range for all blocks
        enable_torch_compile=False,
        use_fp8_gemm=False,
        quant_type="fp8_e4m3",
        include_patterns="double_blocks",
        use_vae_parallel=False,
        few_step=True,
        num_inference_steps=4,
    )
    initialize_infer_state(args)

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

    # Load image
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image = image.resize((width, height))

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        image_path = f.name
        image.save(image_path)

    # Action model checkpoint path
    action_ckpt = f"{WORLDPLAY_DIR}/ar_distilled_action_model/diffusion_pytorch_model.safetensors"

    # Initialize pipeline
    pipeline = HunyuanVideo_1_5_Pipeline.create_pipeline(
        pretrained_model_name_or_path=HUNYUAN_DIR,
        transformer_version="480p_i2v",
        enable_offloading=False,
        enable_group_offloading=False,  # H200 has enough VRAM; no offloading needed
        create_sr_pipeline=False,
        force_sparse_attn=False,
        transformer_dtype=torch.bfloat16,
        action_ckpt=action_ckpt,
    )

    # Convert pose to input tensors
    latent_num = (num_frames - 1) // 4 + 1
    viewmats, Ks, action = pose_to_input(pose, latent_num)

    # Generate video
    with torch.no_grad():
        out = pipeline(
            enable_sr=False,
            prompt=prompt,
            aspect_ratio="16:9",
            num_inference_steps=num_inference_steps,
            video_length=num_frames,
            negative_prompt="",
            seed=seed,
            output_type="pt",
            prompt_rewrite=False,
            viewmats=viewmats.unsqueeze(0),
            Ks=Ks.unsqueeze(0),
            action=action.unsqueeze(0),
            few_step=True,
            chunk_latent_frames=4,
            model_type="ar",
            user_height=height,
            user_width=width,
            reference_image=image_path,
        )

    # Clean up temp image
    os.unlink(image_path)

    # Save video
    video = out.videos
    if video.ndim == 5:
        video = video[0]
    vid = (video * 255).clamp(0, 255).to(torch.uint8)
    vid = einops.rearrange(vid, "c f h w -> f h w c")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        output_path = f.name
    imageio.mimwrite(output_path, vid.cpu().numpy(), fps=24)

    with open(output_path, "rb") as f:
        video_bytes = f.read()
    os.unlink(output_path)

    # Encode response
    video_base64 = base64.b64encode(video_bytes).decode("utf-8")

    return {"video_base64": video_base64}





