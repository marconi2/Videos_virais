#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Aplicação Modal para o projeto Videos_virais (V1).

Modelo: Wan-AI/Wan2.1-I2V-14B-480P-Diffusers  (image-to-video, 480p)
GPU: A100 80GB (bfloat16 nativo). Pico medido ~52 GB.

Estrutura:
  - Volume persistente 'videos-virais-modelos' guarda o modelo (baixa 1 vez).
  - download_model()  -> baixa o Wan para o Volume (CPU, sem gastar GPU).
  - WanRunner (classe) -> carrega o modelo UMA vez por container (@enter) e
    gera clipes reusando o pipeline. Método gerar_lote() faz várias cenas na
    MESMA ligada da GPU (dilui o custo de carregamento).
  - teste_local()      -> testa 1 imagem.
  - gerar_roteiro()    -> entrypoint chamado pelo scripts/generate_video.py.

Comandos:
  modal run modal_app/app.py::download_model
  modal run modal_app/app.py::teste_local --imagem entrada/imagens/personagem1.png
"""

import io
import time

import modal

# --------------------------------------------------------------------------- #
MODEL_ID = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"
MODEL_DIR = "/models/wan21_i2v_14b_480p"
GPU = "A100-80GB"
VOLUME_NAME = "videos-virais-modelos"

NEGATIVE_PADRAO = (
    "Bright tones, overexposed, static, blurred details, subtitles, style, works, "
    "paintings, images, static, overall gray, worst quality, low quality, JPEG "
    "compression residue, ugly, incomplete, extra fingers, poorly drawn hands, poorly "
    "drawn faces, deformed, disfigured, misshapen limbs, fused fingers, still picture, "
    "messy background, three legs, many people in the background, walking backwards"
)

app = modal.App("videos-virais")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "torch",
        "torchvision",
        "diffusers>=0.34.0",
        "transformers",
        "accelerate",
        "safetensors",
        "sentencepiece",
        "ftfy",
        "imageio",
        "imageio-ffmpeg",
        "huggingface_hub",
        "Pillow",
        "numpy",
    )
)


# --------------------------------------------------------------------------- #
# Download do modelo para o Volume (CPU, sem GPU)
# --------------------------------------------------------------------------- #
@app.function(image=image, volumes={"/models": volume}, timeout=60 * 60)
def download_model():
    import os
    from huggingface_hub import snapshot_download

    os.makedirs(MODEL_DIR, exist_ok=True)
    print(f"Baixando {MODEL_ID} -> {MODEL_DIR} ...")
    snapshot_download(repo_id=MODEL_ID, local_dir=MODEL_DIR)
    volume.commit()
    total = sum(
        os.path.getsize(os.path.join(r, f))
        for r, _, fs in os.walk(MODEL_DIR) for f in fs
    )
    print(f"Download concluído. Tamanho total: {total/1024**3:.1f} GB")
    return {"model_dir": MODEL_DIR, "size_gb": round(total / 1024**3, 1)}


# --------------------------------------------------------------------------- #
# Runner: carrega o modelo UMA vez por container e reusa entre cenas
# --------------------------------------------------------------------------- #
@app.cls(
    image=image,
    gpu=GPU,
    volumes={"/models": volume},
    timeout=60 * 60,
    scaledown_window=10,  # desliga a GPU 10s após ficar ociosa
)
class WanRunner:
    @modal.enter()
    def carregar(self):
        """Executado UMA vez quando o container sobe: carrega o Wan na GPU."""
        import torch
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
        from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
        from transformers import CLIPVisionModel

        t0 = time.time()
        image_encoder = CLIPVisionModel.from_pretrained(
            MODEL_DIR, subfolder="image_encoder", torch_dtype=torch.float32
        )
        vae = AutoencoderKLWan.from_pretrained(
            MODEL_DIR, subfolder="vae", torch_dtype=torch.float32
        )
        self.pipe = WanImageToVideoPipeline.from_pretrained(
            MODEL_DIR, vae=vae, image_encoder=image_encoder, torch_dtype=torch.bfloat16
        )
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(
            self.pipe.scheduler.config, flow_shift=3.0  # 3.0 p/ 480P
        )
        self.pipe.to("cuda")
        self._torch = torch
        print(f"[WanRunner] modelo carregado em {time.time()-t0:.0f}s")

    def _gerar(self, imagem_bytes, prompt, duracao_s, fps,
               negative_prompt, guidance_scale, num_inference_steps, seed):
        import numpy as np
        from PIL import Image
        from diffusers.utils import export_to_video
        torch = self._torch

        image = Image.open(io.BytesIO(imagem_bytes)).convert("RGB")
        max_area = 480 * 832
        aspect = image.height / image.width
        mod = self.pipe.vae_scale_factor_spatial * self.pipe.transformer.config.patch_size[1]
        height = round(np.sqrt(max_area * aspect)) // mod * mod
        width = round(np.sqrt(max_area / aspect)) // mod * mod
        image = image.resize((width, height))

        target = max(1, int(round(duracao_s * fps)))
        k = max(1, round((target - 1) / 4))
        num_frames = 4 * k + 1

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        result = self.pipe(
            image=image,
            prompt=prompt,
            negative_prompt=negative_prompt or NEGATIVE_PADRAO,
            height=height, width=width,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=torch.Generator().manual_seed(seed),
        )
        frames = result.frames[0]
        out_path = "/tmp/clipe.mp4"
        export_to_video(frames, out_path, fps=fps)
        with open(out_path, "rb") as f:
            data = f.read()
        peak = torch.cuda.max_memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
        print(f"  clipe {num_frames}f {width}x{height} em {time.time()-t0:.0f}s | "
              f"pico {peak:.1f} GB | {len(data)/1024:.0f} KB")
        return data

    @modal.method()
    def gerar_clipe(self, imagem_bytes: bytes, prompt: str, duracao_s: float = 5.0,
                    fps: int = 16, negative_prompt: str = None,
                    guidance_scale: float = 5.0, num_inference_steps: int = 40,
                    seed: int = 0) -> bytes:
        """Gera 1 clipe (mp4 em bytes)."""
        return self._gerar(imagem_bytes, prompt, duracao_s, fps,
                           negative_prompt, guidance_scale, num_inference_steps, seed)

    @modal.method()
    def gerar_lote(self, cenas: list, fps: int = 16, guidance_scale: float = 5.0,
                   num_inference_steps: int = 40) -> list:
        """Gera VÁRIAS cenas na mesma ligada da GPU (modelo já carregado).

        cenas: lista de dicts com:
          {"id": 1, "imagem_bytes": <bytes>, "prompt": "...",
           "duracao_s": 5.0, "seed": 0}
        Retorna: lista de dicts {"id": 1, "video_bytes": <bytes>}.
        """
        resultados = []
        for c in cenas:
            print(f"[cena {c.get('id')}] gerando...")
            data = self._gerar(
                c["imagem_bytes"], c["prompt"], c.get("duracao_s", 5.0), fps,
                c.get("negative_prompt"), guidance_scale, num_inference_steps,
                c.get("seed", 0),
            )
            resultados.append({"id": c.get("id"), "video_bytes": data})
        return resultados


# --------------------------------------------------------------------------- #
# Montagem final (CPU, sem GPU) — une clipes + narrações em 9:16
# --------------------------------------------------------------------------- #
@app.function(image=image, timeout=60 * 20)
def montar(cenas: list, largura: int = 1080, altura: int = 1920, fps: int = 24) -> bytes:
    """Une os clipes (com narração opcional) num único mp4 vertical 9:16.

    cenas: lista em ORDEM, cada item:
      {"id": 1, "video_bytes": <bytes>, "audio_bytes": <bytes|None>}

    Regra de sincronização (narração em off):
      - Se a cena tem áudio, o clipe é ajustado (corta/estende) para a duração
        do áudio, e o áudio daquela cena é casado com o vídeo daquela cena.
      - Se não tem áudio, mantém a duração do clipe (silêncio).
    Cada cena é padronizada para 9:16 (scale + pad) e depois concatenada.
    Retorna os bytes do video_final.mp4.
    """
    import os
    import subprocess
    import tempfile

    workdir = tempfile.mkdtemp()
    partes = []

    def ff(*args):
        subprocess.run(["ffmpeg", "-y", *args], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for i, c in enumerate(cenas):
        cid = c.get("id", i + 1)
        vpath = os.path.join(workdir, f"v_{i}.mp4")
        with open(vpath, "wb") as f:
            f.write(c["video_bytes"])

        # normaliza vídeo para 9:16 (scale mantendo proporção + pad + fps fixo)
        vf = (
            f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
            f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={fps},setsar=1"
        )
        saida_parte = os.path.join(workdir, f"parte_{i}.mp4")
        audio_bytes = c.get("audio_bytes")

        if audio_bytes:
            apath = os.path.join(workdir, f"a_{i}.mp3")
            with open(apath, "wb") as f:
                f.write(audio_bytes)
            # -shortest casa a duração ao áudio; vídeo faz loop se for mais curto.
            ff("-stream_loop", "-1", "-i", vpath, "-i", apath,
               "-vf", vf, "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-shortest", saida_parte)
        else:
            # sem áudio: adiciona faixa de áudio silenciosa (para concat uniforme)
            ff("-i", vpath, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
               "-vf", vf, "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-shortest", saida_parte)
        partes.append(saida_parte)
        print(f"[montar] cena {cid} normalizada -> {os.path.basename(saida_parte)}")

    # lista para o concat demuxer
    lista = os.path.join(workdir, "concat.txt")
    with open(lista, "w") as f:
        for p in partes:
            f.write(f"file '{p}'\n")

    final = os.path.join(workdir, "video_final.mp4")
    # re-encode no concat para garantir uniformidade dos clipes
    ff("-f", "concat", "-safe", "0", "-i", lista,
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", final)

    with open(final, "rb") as f:
        data = f.read()
    print(f"[montar] video_final: {len(data)/1024:.0f} KB, {len(partes)} cena(s)")
    return data


# --------------------------------------------------------------------------- #
# Teste local rápido (1 imagem)
# --------------------------------------------------------------------------- #
@app.local_entrypoint()
def teste_local(imagem: str, prompt: str = None):
    import pathlib
    if prompt is None:
        prompt = (
            "the character stays mostly still, gentle subtle motion, soft breeze moving "
            "hair slightly, slow cinematic camera push-in, consistent character, high detail"
        )
    img_path = pathlib.Path(imagem)
    if not img_path.exists():
        print(f"[ERRO] imagem não encontrada: {img_path}")
        return
    runner = WanRunner()
    video_bytes = runner.gerar_clipe.remote(img_path.read_bytes(), prompt, duracao_s=5.0)
    saida = pathlib.Path("saida"); saida.mkdir(exist_ok=True)
    out = saida / "teste_wan.mp4"
    out.write_bytes(video_bytes)
    print(f"OK -> {out}  ({len(video_bytes)/1024:.0f} KB)")
