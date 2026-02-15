import modal
import os
import sys

app = modal.App("hy-worldplay")
GPU_CONFIG = "H200:4"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "wget", "curl", "libgl1-mesa-glx", "libglib2.0-0", "ffmpeg")
    .pip_install(
        "torch>=2.2.0",
        "torchvision",
        "transformers",
        "diffusers",
        "accelerate",
        "safetensors",
        "pillow",
        "numpy",
        "opencv-python",
        "einops",
        "omegaconf",
        "sentencepiece",
        "protobuf",
        "peft",
        "huggingface_hub",
        "imageio",
        "imageio-ffmpeg",
        "scipy",
        "loguru",
        "moviepy==1.0.3",
        "decorator",
        "openai",
        "modelscope",
    )
    .add_local_dir(
        "HY-WorldPlay", 
        remote_path="/root/HY-WorldPlay", 
        copy=True,
        ignore=[".git", ".gitignore", "__pycache__", "*.pyc"]
    )
    .add_local_dir(
        "HunyuanVideo-1.5",
        remote_path="/root/HunyuanVideo-1.5",
        copy=True,
        ignore=[".git", ".gitignore", "__pycache__", "*.pyc"]
    )
    .env({
        "PYTHONPATH": "/root/HY-WorldPlay:$PYTHONPATH",
        "SAFETENSORS_DISABLE_MMAP": "1"
    })
)

volume = modal.Volume.from_name("hy-worldplay-models", create_if_missing=True)

# 直接读取 .env 文件
hf_token = ""
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("HF_TOKEN="):
                hf_token = line.split("=", 1)[1].strip()
                break

hf_secret = modal.Secret.from_dict({"HF_TOKEN": hf_token})


@app.cls(
    image=image,
    gpu=GPU_CONFIG,
    volumes={"/models": volume},
    timeout=3600,
    secrets=[hf_secret],
)
class WorldPlay:
    @modal.enter()
    def setup(self):
        import os

        import torch
        from huggingface_hub import hf_hub_download

        sys.path.insert(0, "/root/HY-WorldPlay")
        
        base_model_path = "/models/HunyuanVideo"
        os.makedirs(base_model_path, exist_ok=True)

        must_have_safetensors = "/models/HunyuanVideo/transformer/480p_i2v/diffusion_pytorch_model.safetensors"
        must_have_bin = "/models/HunyuanVideo/transformer/480p_i2v/diffusion_pytorch_model.bin"

        def download_one_and_commit(filename: str) -> None:
            local_path = os.path.join(base_model_path, filename)
            if os.path.exists(local_path):
                print(f"skip exists {filename}")
                return

            parent = os.path.dirname(local_path)
            os.makedirs(parent, exist_ok=True)

            print(f"downloading {filename}")
            hf_hub_download(
                repo_id="tencent/HunyuanVideo-1.5",
                filename=filename,
                local_dir=base_model_path,
                token=os.environ.get("HF_TOKEN"),
                local_dir_use_symlinks=False,
            )
            print("commit volume")
            volume.commit()

        if (not os.path.exists(must_have_safetensors)) and (not os.path.exists(must_have_bin)):
            print("base missing transformer weights, downloading one by one with commit")

            base_files = [
                "config.json",
            ]

            scheduler_files = [
                "scheduler/scheduler_config.json",
            ]

            vae_files = [
                "vae/config.json",
            ]

            transformer_files = [
                "transformer/480p_i2v/config.json",
            ]

            for f in base_files + scheduler_files + vae_files + transformer_files:
                try:
                    download_one_and_commit(f)
                except Exception as e:
                    print(f"warning failed {f}: {e}")

            weight_candidates = [
                "transformer/480p_i2v/diffusion_pytorch_model.safetensors",
                "transformer/480p_i2v/diffusion_pytorch_model.bin",
                "transformers/480p_i2v/diffusion_pytorch_model.safetensors",
                "transformers/480p_i2v/diffusion_pytorch_model.bin",
            ]

            weight_ok = False
            last_err = None
            for w in weight_candidates:
                try:
                    download_one_and_commit(w)
                    weight_ok = True
                    break
                except Exception as e:
                    last_err = e

            if not weight_ok:
                raise RuntimeError(f"failed to download transformer weight file, last error: {last_err}")

            if (not os.path.exists(must_have_safetensors)) and (not os.path.exists(must_have_bin)):
                alt_safetensors = "/models/HunyuanVideo/transformers/480p_i2v/diffusion_pytorch_model.safetensors"
                alt_bin = "/models/HunyuanVideo/transformers/480p_i2v/diffusion_pytorch_model.bin"
                if os.path.exists(alt_safetensors) or os.path.exists(alt_bin):
                    os.makedirs("/models/HunyuanVideo/transformer/480p_i2v", exist_ok=True)
                    if os.path.exists(alt_safetensors) and (not os.path.exists(must_have_safetensors)):
                        import shutil

                        shutil.copy2(alt_safetensors, must_have_safetensors)
                        volume.commit()
                    if os.path.exists(alt_bin) and (not os.path.exists(must_have_bin)):
                        import shutil

                        shutil.copy2(alt_bin, must_have_bin)
                        volume.commit()

            print("base download done")
        
        # 按照 HY-WorldPlay download_models.py 的方式下载所有模型
        print("Downloading models following HY-WorldPlay official method...")
        from huggingface_hub import snapshot_download
        
        # 1. 下载 HunyuanVideo-1.5 基础模型
        print("Downloading HunyuanVideo-1.5 base model...")
        snapshot_download(
            "tencent/HunyuanVideo-1.5",
            allow_patterns=["vae/*", "scheduler/*", "transformer/480p_i2v/*"],
            local_dir="/models/HunyuanVideo",
        )
        
        # 2. 下载 Qwen2.5-VL-7B-Instruct (hidden_size=3584)
        text_encoder_llm_path = "/models/HunyuanVideo/text_encoder/llm"
        if not os.path.exists(os.path.join(text_encoder_llm_path, "config.json")):
            print("Downloading Qwen2.5-VL-7B-Instruct...")
            snapshot_download(
                "Qwen/Qwen2.5-VL-7B-Instruct",
                local_dir=text_encoder_llm_path,
            )
        
        # 3. 下载 byt5-small
        byt5_path = "/models/HunyuanVideo/text_encoder/byt5-small"
        if not os.path.exists(os.path.join(byt5_path, "config.json")):
            print("Downloading byt5-small...")
            snapshot_download(
                "google/byt5-small",
                local_dir=byt5_path,
            )
        
        # 4. 下载 Glyph-SDXL-v2
        glyph_path = "/models/HunyuanVideo/text_encoder/Glyph-SDXL-v2"
        if not os.path.exists(os.path.join(glyph_path, "checkpoints", "byt5_model.pt")):
            print("Downloading Glyph-SDXL-v2...")
            try:
                from modelscope import snapshot_download as ms_snapshot_download
                ms_snapshot_download(
                    "AI-ModelScope/Glyph-SDXL-v2",
                    local_dir=glyph_path,
                )
            except Exception as e:
                print(f"Warning: Glyph-SDXL-v2 download failed: {e}")
        
        # 5. 下载 vision encoder (使用 google/siglip 而不是 FLUX)
        vision_encoder_path = "/models/HunyuanVideo/vision_encoder/siglip"
        if not os.path.exists(vision_encoder_path):
            print("Downloading SigLIP vision encoder...")
            os.makedirs(vision_encoder_path, exist_ok=True)
            # 直接下载整个 siglip 模型
            snapshot_download(
                "google/siglip-so400m-patch14-384",
                local_dir=vision_encoder_path,
            )
        
        # 6. 下载 HY-WorldPlay action checkpoint
        action_ckpt_file = "/models/HunyuanVideo/ar_distilled_action_model/model.safetensors"
        if not os.path.exists(action_ckpt_file):
            print("Downloading HY-WorldPlay action checkpoint...")
            hf_hub_download(
                repo_id="tencent/HY-WorldPlay",
                filename="ar_distilled_action_model/model.safetensors",
                local_dir="/models/HunyuanVideo",
                token=os.environ.get("HF_TOKEN"),
                local_dir_use_symlinks=False,
            )
        
        volume.commit()
        print("All models downloaded")
        
        # 删除旧的 vision encoder 下载代码（已经在上面统一下载了）
        
        from hyvideo.commons.parallel_states import initialize_parallel_state
        from hyvideo.commons.infer_state import initialize_infer_state
        from hyvideo.pipelines.worldplay_video_pipeline import HunyuanVideo_1_5_Pipeline

        os.environ["WORLD_SIZE"] = "1"
        os.environ["RANK"] = "0"
        os.environ["LOCAL_RANK"] = "0"
        torch.cuda.set_device(0)

        initialize_parallel_state(sp=1)

        class Args:
            def __init__(self):
                self.use_sageattn = False
                self.sage_blocks_range = "0-53"
                self.use_vae_parallel = False
                self.use_fp8_gemm = False
                self.quant_type = "fp8-per-block"
                self.include_patterns = "double_blocks"
                self.enable_torch_compile = False
                self.use_cpu_offload = False

        initialize_infer_state(Args())

        print("Loading WorldPlay pipeline (without action checkpoint for now)...")
        self.pipe = HunyuanVideo_1_5_Pipeline.create_pipeline(
            pretrained_model_name_or_path=base_model_path,
            transformer_version="480p_i2v",
            enable_offloading=True,
            transformer_dtype=torch.bfloat16,
            action_ckpt=None,  # 先不用 action checkpoint，让基础模型跑起来
        )

        import numpy as np

        self.pipe.points_local = np.array(
            [[0, 0], [0, 1], [1, 0], [1, 1], [0.5, 0.5], [0.25, 0.25], [0.75, 0.75]]
        )
        print("Pipeline loaded and ready!")

    @modal.method()
    def generate(
        self,
        input_image_bytes: bytes,
        prompt: str = "A cinematic camera moving forward through a beautiful natural landscape",
        pose_sequence: str = "w-31",
        num_frames: int = 125,  # 125帧 @ 24fps = 约5秒视频
        seed: int = 42,
    ):
        import torch
        from PIL import Image
        import imageio
        import numpy as np
        from io import BytesIO
        import einops
        
        # 从 bytes 加载图片
        input_image = Image.open(BytesIO(input_image_bytes)).convert("RGB")
        
        # 使用 HY-WorldPlay 的 generate 接口
        from hyvideo.generate import pose_to_input
        
        # 验证 num_frames
        assert (num_frames - 1) % 4 == 0, f"(num_frames-1) must be divisible by 4, got {num_frames}"
        latent_num = (num_frames - 1) // 4 + 1
        assert latent_num % 4 == 0, f"latent_num must be divisible by 4, got {latent_num}"
        
        viewmats, Ks, action = pose_to_input(pose_sequence, latent_num)
        
        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        # 调用 pipeline 生成视频（参考 generate.py 的调用方式）
        output = self.pipe(
            enable_sr=False,
            prompt=prompt,
            aspect_ratio="16:9",  # 480p i2v 使用 16:9
            num_inference_steps=4,  # distilled model 使用 4 steps
            sr_num_inference_steps=None,
            video_length=num_frames,
            negative_prompt="",
            seed=seed,
            output_type="pt",
            prompt_rewrite=False,  # 禁用 prompt rewrite
            return_pre_sr_video=False,
            viewmats=viewmats.unsqueeze(0),
            Ks=Ks.unsqueeze(0),
            action=action.unsqueeze(0),
            few_step=True,  # distilled model
            chunk_latent_frames=4,  # ar model 使用 4
            model_type="ar",
            user_height=480,
            user_width=832,
            reference_image=input_image,
        )
        
        # 保存视频
        video = output.videos
        if video.ndim == 5:
            assert video.shape[0] == 1
            video = video[0]
        vid = (video * 255).clamp(0, 255).to(torch.uint8)
        vid = einops.rearrange(vid, "c f h w -> f h w c")
        
        output_path = "/tmp/output.mp4"
        imageio.mimwrite(output_path, vid, fps=24)
        
        # 读取并返回视频文件
        with open(output_path, "rb") as f:
            video_bytes = f.read()
        
        return video_bytes


@app.local_entrypoint()
def main(prompt: str = "A cinematic camera moving forward through a beautiful natural landscape", pose: str = "w-31"):
    
    # 读取 input.jpg
    if not os.path.exists("input.jpg"):
        print("Error: input.jpg not found in current directory")
        return
    
    with open("input.jpg", "rb") as f:
        input_data = f.read()
    
    worldplay = WorldPlay()
    
    print(f"Generating video with prompt: {prompt}, pose: {pose}")
    video_bytes = worldplay.generate.remote(
        input_image_bytes=input_data,
        prompt=prompt,
        pose_sequence=pose
    )
    
    # 保存输出视频
    with open("output.mp4", "wb") as f:
        f.write(video_bytes)
    
    print("Video saved to output.mp4")