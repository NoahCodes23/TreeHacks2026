import modal

APP_NAME = "hy-worldplay"
REPO_DIR = "/root/HY-WorldPlay"
MODEL_DIR = "/root/models"

# Persistent storage for huge weights
model_volume = modal.Volume.from_name("hy-worldplay-models", create_if_missing=True)

# -------------------------
# Container image
# -------------------------
image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.1.1-devel-ubuntu22.04",
        add_python="3.10",
    )
    # System deps (README style)
    .apt_install(
        "git",
        "ffmpeg",
        "libgl1"
    )
    # Install PyTorch first (same order as README)
    .pip_install(
        "torch",
        "torchvision",
        "torchaudio",
        extra_index_url="https://download.pytorch.org/whl/cu121",
    )
    # Clone repo
    .run_commands(
        f"git clone https://github.com/Tencent-Hunyuan/HY-WorldPlay.git {REPO_DIR}",
        f"pip install -r {REPO_DIR}/requirements.txt",
    )
)

app = modal.App(APP_NAME, image=image)


# -------------------------
# Step 1: Download models
# -------------------------
@app.function(
    volumes={MODEL_DIR: model_volume},
    timeout=7200,
    gpu="A100"
)
def download_models(hf_token: str, skip_vision: bool = True):
    import subprocess
    import os

    os.chdir(REPO_DIR)

    cmd = [
        "python",
        "download_models.py",
        "--hf_token",
        hf_token,
        "--save_dir",
        MODEL_DIR,
    ]

    if skip_vision:
        cmd.append("--skip_vision_encoder")

    subprocess.run(cmd, check=True)


# -------------------------
# Step 2: Run HY-WorldPlay
# -------------------------
@app.function(
    gpu="A100",
    timeout=3600,
    volumes={MODEL_DIR: model_volume},
)
def run_worldplay():
    import subprocess
    import os

    os.chdir(REPO_DIR)

    # Environment variables like local setup
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    # The README uses run.sh
    subprocess.run(["bash", "run.sh"], check=True)


# -------------------------
# Local entrypoint
# -------------------------
@app.local_entrypoint()
def main(
    hf_token: str,
):
    # Download once (persistent)
    download_models.remote(hf_token)

    # Start world model
    run_worldplay.remote()
