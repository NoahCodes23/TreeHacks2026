# Running HY-WorldPlay on Modal

[Modal](https://modal.com) is a serverless cloud platform that makes it easy to run GPU workloads. This guide explains how to deploy and run HY-WorldPlay on Modal.

## Prerequisites

1. **Modal Account**: Sign up at [modal.com](https://modal.com) (free tier includes $30/month of compute credits)
2. **HuggingFace Token**: Required for downloading the vision encoder from FLUX.1-Redux-dev
   - Request access at: https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev
   - Get your token at: https://huggingface.co/settings/tokens

## Setup

### 1. Install Modal

```bash
pip install modal
```

### 2. Authenticate with Modal

```bash
modal setup
```

This opens a browser window for authentication.

### 3. Create HuggingFace Secret

Store your HuggingFace token as a Modal secret:

```bash
modal secret create huggingface-secret HF_TOKEN=<your_huggingface_token>
```

### 4. Download Models to Modal Volume

This downloads all required models (~100GB) to a persistent Modal volume:

```bash
modal run modal_app.py::download_models
```

This step takes 30-60 minutes depending on your network speed. The models are stored persistently, so you only need to do this once.

### 5. Upload Code to Modal Volume

Upload the project code to Modal:

```bash
modal volume put hy-worldplay-code ./hyvideo /hyvideo
modal volume put hy-worldplay-code ./trainer /trainer
modal volume put hy-worldplay-code ./wan /wan
```

Or use the sync command:

```bash
modal run modal_app.py::sync_code
```

**Note:** You need to re-run this step whenever you modify the code.

## Usage

### Command Line Inference

Generate a video from a local image:

```bash
modal run modal_app.py::generate \
    --image-path ./assets/img/test.png \
    --prompt "A paved pathway leads towards a stone arch bridge spanning a calm body of water." \
    --pose "w-31" \
    --output-path ./outputs/modal_output.mp4
```

#### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--image-path` | Path to input image | `./assets/img/test.png` |
| `--prompt` | Text description of the scene | Required |
| `--pose` | Camera trajectory (e.g., `w-31` for forward) | `w-31` |
| `--num-frames` | Number of frames to generate | `125` |
| `--seed` | Random seed for reproducibility | `42` |
| `--output-path` | Where to save the output video | `./outputs/modal_output.mp4` |

#### Camera Trajectory (Pose) Options

- `w-N`: Move forward for N latent frames
- `s-N`: Move backward
- `a-N`: Move left
- `d-N`: Move right
- `up-N`: Pitch up
- `down-N`: Pitch down
- `left-N`: Yaw left
- `right-N`: Yaw right

You can combine movements: `w-15, right-8, w-8`

### Deploy as Web API

Deploy a persistent web endpoint:

```bash
modal deploy modal_app.py
```

This creates an HTTPS endpoint that you can call from anywhere:

```python
import requests
import base64

# Read and encode image
with open("image.png", "rb") as f:
    image_base64 = base64.b64encode(f.read()).decode()

# Call the API
response = requests.post(
    "https://your-modal-endpoint.modal.run",
    json={
        "image_base64": image_base64,
        "prompt": "A beautiful garden scene",
        "pose": "w-31",
        "num_frames": 125,
        "seed": 42
    }
)

# Decode and save video
video_base64 = response.json()["video_base64"]
video_bytes = base64.b64decode(video_base64)
with open("output.mp4", "wb") as f:
    f.write(video_bytes)
```

## GPU Options

The default configuration uses 4x H200 GPUs with sequence parallelism for fast inference. You can modify `modal_app.py` to use different GPUs:

```python
# In modal_app.py, change the gpu parameter:

# 4x H200 (default, fastest)
gpu=modal.gpu.H200(count=4)

# 8x H200 (maximum parallelism)
gpu=modal.gpu.H200(count=8)

# 4x A100 80GB (alternative)
gpu=modal.gpu.A100(count=4, size="80GB")

# 1x A100 80GB (single GPU, slower but cheaper)
gpu=modal.gpu.A100(count=1, size="80GB")
```

When changing GPU count, also update the sequence parallelism (sp) value in `initialize_parallel_state(sp=N)` to match.

## Multi-GPU Inference

The default configuration uses 4x H200 GPUs with sequence parallelism (sp=4) for optimal performance. To use a different number of GPUs:

1. Change the `gpu` parameter in `@app.cls` and `@app.function` decorators
2. Update `os.environ["WORLD_SIZE"]` to match the GPU count
3. Update `initialize_parallel_state(sp=N)` where N equals the GPU count

Example for 8 GPUs:
```python
@app.cls(
    image=image,
    gpu=modal.gpu.H200(count=8),  # 8 GPUs
    volumes={MODELS_DIR: model_volume},
    timeout=1800,
)
class WorldPlayInference:
    @modal.enter()
    def load_model(self):
        # Set for 8 GPU parallel
        os.environ["WORLD_SIZE"] = "8"
        initialize_parallel_state(sp=8)
        # ... rest of the code
```

## Cost Estimation

Modal charges based on compute time:

| GPU | Price/hour | Typical inference time | Cost per video |
|-----|------------|------------------------|----------------|
| 4x H200 | ~$16.00 | ~30-60 sec | ~$0.15-0.30 |
| 4x A100 80GB | ~$12.00 | ~1-2 min | ~$0.20-0.40 |
| 1x A100 80GB | ~$3.00 | ~3-5 min | ~$0.15-0.25 |

*Prices are approximate and may change. Check [Modal pricing](https://modal.com/pricing) for current rates.*

## Troubleshooting

### "Model not found" error

Make sure you've run the model download step:
```bash
modal run modal_app.py::download_models
```

### "No access to FLUX.1-Redux-dev"

1. Request access at https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev
2. Wait for approval (usually instant)
3. Update your Modal secret with a valid HF token

### Out of memory errors

Try reducing `num_frames` or using a GPU with more memory:
```bash
modal run modal_app.py::generate --num-frames 61
```

### Slow cold start

Modal containers need to start up and load models on first request. Use `container_idle_timeout` to keep containers warm between requests.

## Advanced: Local Development

To test changes locally before deploying:

```bash
# Run in local mode (still uses Modal for GPU)
modal run --detach modal_app.py::generate
```

## Files

- `modal_app.py` - Main Modal application with inference code
- `MODAL_README.md` - This documentation file

