"""
Complete Modal Deployment for HY-WorldPlay
https://github.com/Tencent-Hunyuan/HY-WorldPlay/

Single script that handles installation, model downloads, and inference.
Based on the official README documentation.

Usage:
    # First time setup - download models (~100GB, takes 30-60 min)
    modal run hyworld_modal.py::download_models
    
    # Generate a video
    modal run hyworld_modal.py::generate --prompt "A forest path" --pose "w-31"
    
    # Deploy as web API
    modal deploy hyworld_modal.py
"""

import modal
import os

app = modal.App("hy-worldplay")

# Volumes for persistent storage
models_volume = modal.Volume.from_name("hyworld-models", create_if_missing=True)
outputs_volume = modal.Volume.from_name("hyworld-outputs", create_if_missing=True)

# Build the container image with all dependencies
image = (
    modal.Image.debian_slim(python_version="3.10")
    # Install system dependencies
    .apt_install(
        "git",
        "wget", 
        "ffmpeg",
        "libgl1-mesa-glx",
        "libglib2.0-0",
        "libsm6",
        "libxext6",
        "libxrender-dev",
        "libgomp1",
        "build-essential",
    )
    # Clone the repository
    .run_commands(
        "git clone https://github.com/Tencent-Hunyuan/HY-WorldPlay.git /root/HY-WorldPlay",
    )
    # Install Python dependencies from requirements.txt
    .run_commands(
        "cd /root/HY-WorldPlay && pip install -r requirements.txt",
    )
    # Install optional optimizations
    .run_commands(
        # Flash Attention for faster inference
        "pip install flash-attn --no-build-isolation || echo 'Flash attention install failed, continuing...'",
        # AngelSlim for quantization
        "pip install angelslim==0.2.2 || echo 'AngelSlim install failed, continuing...'",
    )
)


@app.function(
    image=image,
    gpu=modal.gpu.A100(size="80GB"),
    timeout=7200,  # 2 hours for downloading
    volumes={"/root/models": models_volume},
    secrets=[modal.Secret.from_name("huggingface-secret")],
)
def download_models():
    """
    Download all required models (~100GB total).
    Requires HuggingFace token with FLUX.1-Redux-dev access.
    
    Before running:
    1. Get HF token: https://huggingface.co/settings/tokens
    2. Request FLUX access: https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev
    3. Create Modal secret: modal secret create huggingface-secret HF_TOKEN=<your_token>
    """
    import subprocess
    import sys
    
    os.chdir("/root/HY-WorldPlay")
    
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise ValueError(
            "HF_TOKEN not found. Create it with:\n"
            "modal secret create huggingface-secret HF_TOKEN=<your_token>"
        )
    
    print("=" * 80)
    print("Downloading models (this will take 30-60 minutes)...")
    print("=" * 80)
    
    result = subprocess.run(
        [sys.executable, "download_models.py", "--hf_token", hf_token],
        capture_output=True,
        text=True,
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode != 0:
        raise RuntimeError(f"Model download failed: {result.stderr}")
    
    # Commit to persist models
    models_volume.commit()
    
    print("\n" + "=" * 80)
    print("✅ Models downloaded successfully!")
    print("=" * 80)
    
    return "Models downloaded and cached"


@app.function(
    image=image,
    gpu=modal.gpu.A100(size="80GB"),
    timeout=1800,  # 30 minutes
    volumes={
        "/root/models": models_volume,
        "/root/outputs": outputs_volume,
    },
)
def generate(
    prompt: str = "A serene mountain landscape with a winding path",
    pose: str = "w-31",
    num_frames: int = 125,
    model_type: str = "ar_distilled",
    image_path: str = None,
    seed: int = 42,
    output_name: str = "output.mp4",
):
    """
    Generate a video with HY-WorldPlay.
    
    Args:
        prompt: Scene description
        pose: Camera movement (e.g., "w-31", "w-10,right-2,d-5")
              Actions: w/s/a/d (move), up/down/left/right (rotate)
        num_frames: Must satisfy (num_frames-1) % 4 == 0 (e.g., 125, 81, 49)
        model_type: "ar_distilled" (fast), "ar" (balanced), or "bi" (best quality)
        image_path: Optional input image for I2V mode
        seed: Random seed
        output_name: Output filename
    
    Returns:
        Path to generated video
    """
    import subprocess
    import sys
    import glob
    import shutil
    
    os.chdir("/root/HY-WorldPlay")
    
    # Validate frames
    if (num_frames - 1) % 4 != 0:
        raise ValueError(
            f"num_frames must satisfy (num_frames-1) % 4 == 0. "
            f"Got {num_frames}. Try: 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 73, 77, 81, 85, 89, 93, 97, 101, 105, 109, 113, 117, 121, 125"
        )
    
    print("=" * 80)
    print(f"Generating video...")
    print(f"Prompt: {prompt}")
    print(f"Camera: {pose}")
    print(f"Frames: {num_frames}")
    print(f"Model: {model_type}")
    print("=" * 80)
    
    # Find downloaded models
    model_dirs = glob.glob("/root/models/**/HY-WorldPlay", recursive=True)
    if not model_dirs:
        model_dirs = glob.glob("/root/models/**/HunyuanVideo*", recursive=True)
    
    if not model_dirs:
        raise RuntimeError(
            "Models not found. Run download_models first:\n"
            "modal run hyworld_modal.py::download_models"
        )
    
    # Determine paths based on actual downloaded structure
    # The download_models.py script puts models in ckpts/
    base_model_path = None
    action_model_base = None
    
    for possible_path in [
        "/root/models/ckpts",
        "/root/models", 
        os.path.dirname(model_dirs[0]),
    ]:
        hunyuan_path = os.path.join(possible_path, "HunyuanVideo-1.5")
        worldplay_path = os.path.join(possible_path, "HY-WorldPlay")
        
        if os.path.exists(hunyuan_path):
            base_model_path = hunyuan_path
        if os.path.exists(worldplay_path):
            action_model_base = worldplay_path
    
    if not base_model_path:
        base_model_path = "/root/models/ckpts/HunyuanVideo-1.5"
        print(f"Warning: Using default base model path: {base_model_path}")
    
    if not action_model_base:
        action_model_base = "/root/models/ckpts/HY-WorldPlay"
        print(f"Warning: Using default action model path: {action_model_base}")
    
    # Select action model
    if model_type == "bi":
        action_ckpt = f"{action_model_base}/bidirectional_model"
        num_inference_steps = 50
        few_step = False
    elif model_type == "ar":
        action_ckpt = f"{action_model_base}/ar_model"
        num_inference_steps = 50
        few_step = False
    elif model_type == "ar_distilled":
        action_ckpt = f"{action_model_base}/ar_distilled_action_model"
        num_inference_steps = 4
        few_step = True
        model_type = "ar"  # Use ar type for distilled
    else:
        raise ValueError(f"Unknown model_type: {model_type}")
    
    print(f"Base model: {base_model_path}")
    print(f"Action model: {action_ckpt}")
    
    # Build inference command
    # Based on run.sh from the repo
    cmd = [
        sys.executable,
        "sample/sample_video.py",
        "--model_path", base_model_path,
        "--action_ckpt", action_ckpt,
        "--model_type", model_type,
        "--prompt", prompt,
        "--pose", pose,
        "--num_frames", str(num_frames),
        "--num_inference_steps", str(num_inference_steps),
        "--seed", str(seed),
    ]
    
    if few_step:
        cmd.extend(["--few_step", "true"])
    
    if image_path:
        cmd.extend(["--image_path", image_path])
    
    print(f"\nRunning: {' '.join(cmd)}\n")
    
    # Run inference
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode != 0:
        raise RuntimeError(f"Generation failed with code {result.returncode}")
    
    # Find generated video
    # The script outputs to ./results/ by default
    possible_outputs = [
        f"./results/{output_name}",
        f"./results/output.mp4",
        "./results/sample.mp4",
    ]
    
    # Also find any recently created mp4
    recent_videos = glob.glob("./results/*.mp4") + glob.glob("./*.mp4")
    recent_videos.sort(key=os.path.getmtime, reverse=True)
    
    output_file = None
    for path in possible_outputs + recent_videos[:3]:
        if os.path.exists(path):
            output_file = path
            break
    
    if not output_file:
        # List what we have
        print("\nSearched for output in:")
        for p in possible_outputs:
            print(f"  {p} - exists: {os.path.exists(p)}")
        print("\nRecent mp4 files:")
        for v in recent_videos[:5]:
            print(f"  {v}")
        raise RuntimeError("Could not find generated video")
    
    # Copy to outputs volume
    output_path = f"/root/outputs/{output_name}"
    os.makedirs("/root/outputs", exist_ok=True)
    shutil.copy(output_file, output_path)
    
    outputs_volume.commit()
    
    print("\n" + "=" * 80)
    print(f"✅ Video generated successfully!")
    print(f"Output: {output_path}")
    print("=" * 80)
    print(f"\nDownload with:")
    print(f"modal volume get hyworld-outputs {output_name} ./{output_name}")
    
    return output_path


@app.function(
    image=image,
    gpu=modal.gpu.A100(size="80GB"),
    timeout=1800,
    volumes={
        "/root/models": models_volume,
        "/root/outputs": outputs_volume,
    },
)
@modal.web_endpoint(method="POST")
def api(data: dict):
    """
    Web API endpoint for video generation.
    
    POST JSON:
    {
        "prompt": "A mountain path",
        "pose": "w-31",
        "model_type": "ar_distilled",
        "num_frames": 125,
        "seed": 42
    }
    
    Returns:
    {
        "status": "success",
        "output_path": "/root/outputs/...",
        "download_cmd": "modal volume get ..."
    }
    """
    try:
        output_path = generate.local(
            prompt=data.get("prompt", "A beautiful landscape"),
            pose=data.get("pose", "w-31"),
            num_frames=data.get("num_frames", 125),
            model_type=data.get("model_type", "ar_distilled"),
            seed=data.get("seed", 42),
            output_name=data.get("output_name", "api_output.mp4"),
        )
        
        filename = os.path.basename(output_path)
        
        return {
            "status": "success",
            "output_path": output_path,
            "download_cmd": f"modal volume get hyworld-outputs {filename} ./{filename}",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@app.local_entrypoint()
def main(
    prompt: str = "A serene mountain landscape with a winding path",
    pose: str = "w-31",
    model_type: str = "ar_distilled",
    num_frames: int = 125,
):
    """
    CLI entrypoint for local testing.
    
    Examples:
        # Download models first
        modal run hyworld_modal.py::download_models
        
        # Generate video
        modal run hyworld_modal.py --prompt "A forest path"
        
        # Custom camera movement
        modal run hyworld_modal.py --prompt "City street" --pose "w-10,right-2,d-5"
        
        # High quality
        modal run hyworld_modal.py --model-type ar --prompt "Mountain view"
    """
    print("\n" + "=" * 80)
    print("HY-WorldPlay on Modal")
    print("=" * 80)
    
    output_path = generate.remote(
        prompt=prompt,
        pose=pose,
        model_type=model_type,
        num_frames=num_frames,
    )
    
    print(f"\n✅ Complete! Output: {output_path}")


# Convenience function for batch generation
@app.function(
    image=image,
    gpu=modal.gpu.A100(size="80GB"),
    timeout=3600,
    volumes={
        "/root/models": models_volume,
        "/root/outputs": outputs_volume,
    },
)
def batch_generate(prompts: list[tuple[str, str]]):
    """
    Generate multiple videos in sequence.
    
    Args:
        prompts: List of (prompt, pose) tuples
    
    Example:
        batch_generate.remote([
            ("Forest path", "w-20"),
            ("City street", "w-10,right-2,d-5"),
            ("Desert landscape", "w-15,up-3"),
        ])
    """
    results = []
    for i, (prompt, pose) in enumerate(prompts):
        print(f"\n{'='*80}\nGenerating {i+1}/{len(prompts)}: {prompt}\n{'='*80}")
        output_path = generate.local(
            prompt=prompt,
            pose=pose,
            output_name=f"batch_{i:03d}.mp4",
        )
        results.append(output_path)
    
    return results
