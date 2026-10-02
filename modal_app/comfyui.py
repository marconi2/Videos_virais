#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comfyui.py — ComfyUI INTERATIVO na T4 do Modal (laboratorio de aprendizado).

Baseado na abordagem comprovada (comfy-cli + `comfy launch`), que faz o PREVIEW
das imagens funcionar corretamente atras do proxy do Modal — diferente de subir
com `python main.py` direto (que gerava a imagem mas nao mostrava no preview).

CUSTO: o ComfyUI roda DENTRO da T4 (~US$ 0,59/h). Paga-se a GPU o tempo TODO que a
UI esta de pe. Freios: scaledown_window=60, timeout=3600, max_containers=1.
DISCIPLINA: ao terminar, Ctrl+C e/ou `modal app stop comfyui-aprendizado`.

MODELOS: no Volume 'videos-virais-modelos', subpasta /vol/comfyui (checkpoints etc.).
O epiCRealism e baixado para la por download_epicrealism (Secret CIVITAI_TOKEN).

COMANDOS:
  modal run modal_app/comfyui.py::download_epicrealism
  modal serve modal_app/comfyui.py
  modal app stop comfyui-aprendizado
"""

import subprocess

import modal

# --------------------------------------------------------------------------- #
VOLUME_NAME = "videos-virais-modelos"
MODELS_ROOT = "/vol/comfyui"   # modelos do ComfyUI no Volume (persistente)
GPU = "T4"
PORT = 8000

app = modal.App("comfyui-aprendizado")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# Imagem com ComfyUI instalado via comfy-cli (abordagem comprovada no Modal).
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "libgl1-mesa-glx", "libglib2.0-0")
    .pip_install("comfy-cli")
    .run_commands("comfy --skip-prompt install --nvidia")
    # ComfyUI-Manager (gerenciar nodes pela UI)
    .run_commands("comfy node install comfyui-manager")
)


# --------------------------------------------------------------------------- #
# Download do epiCRealism para o Volume (CPU, barato — roda uma vez)
# --------------------------------------------------------------------------- #
@app.function(
    image=image,
    volumes={"/vol": volume},
    timeout=60 * 30,
    secrets=[modal.Secret.from_name("civitai")],
)
def download_epicrealism():
    import os

    ckpt_dir = MODELS_ROOT + "/checkpoints"
    os.makedirs(ckpt_dir, exist_ok=True)
    destino = ckpt_dir + "/epicrealism_naturalSinRC1VAE.safetensors"
    if os.path.exists(destino):
        print(">> epiCRealism ja existe no Volume")
        return

    token = os.environ.get("CIVITAI_TOKEN", "")
    if not token:
        print(">> [ERRO] CIVITAI_TOKEN ausente no Secret 'civitai'.")
        return

    url = "https://civitai.com/api/download/models/143906?token=" + token
    print(">> Baixando epiCRealism para o Volume...")
    subprocess.run(["wget", "--content-disposition", url, "-O", destino], check=True)
    volume.commit()
    size = os.path.getsize(destino) / 1024**3
    print(f">> epiCRealism pronto no Volume: {size:.2f} GB")


# --------------------------------------------------------------------------- #
# ComfyUI interativo (web) via `comfy launch`. Preview funciona nesta abordagem.
# --------------------------------------------------------------------------- #
@app.function(
    image=image,
    gpu=GPU,
    volumes={"/vol": volume},
    timeout=3600,
    scaledown_window=60,
    max_containers=1,
)
@modal.concurrent(max_inputs=100)
@modal.web_server(PORT, startup_timeout=120)
def ui():
    import os

    # Garante as pastas de modelos no Volume.
    for sub in ("checkpoints", "loras", "vae", "clip", "unet", "controlnet",
                "upscale_models", "embeddings"):
        os.makedirs(f"{MODELS_ROOT}/{sub}", exist_ok=True)

    # Aponta o ComfyUI (instalado pelo comfy-cli em /root/comfy/ComfyUI) para os
    # modelos do Volume via extra_model_paths.yaml.
    comfy_dir = "/root/comfy/ComfyUI"
    yaml = f"""volume_models:
    base_path: {MODELS_ROOT}
    checkpoints: checkpoints
    loras: loras
    vae: vae
    clip: clip
    unet: unet
    controlnet: controlnet
    upscale_models: upscale_models
    embeddings: embeddings
"""
    try:
        with open(f"{comfy_dir}/extra_model_paths.yaml", "w") as f:
            f.write(yaml)
    except Exception as e:
        print("aviso: nao consegui escrever extra_model_paths.yaml:", e)

    # Sobe o ComfyUI via comfy-cli (faz o preview funcionar atras do proxy Modal).
    subprocess.Popen(
        f"comfy launch -- --listen 0.0.0.0 --port {PORT}",
        shell=True,
    )
