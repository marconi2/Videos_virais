#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comfyui.py — ComfyUI INTERATIVO na T4 do Modal (laboratorio de aprendizado).

Objetivo: aprender ComfyUI (montar workflow, nos, sampler, prompts) gerando
IMAGENS com a T4 do Modal, acessivel pelo navegador. Usa os US$ 30/mes de credito.

IMPORTANTE SOBRE CUSTO (leia):
- Aqui o ComfyUI roda DENTRO da T4. Voce paga a GPU o TEMPO TODO que a UI esta de
  pe (montando workflow, pensando, gerando) — NAO so na geracao. T4 ~US$ 0,59/h.
- FREIOS embutidos para nao faturar parado:
    * scaledown_window=60  -> apos 60s sem requisicao, o container cai (para de cobrar)
    * timeout=3600         -> trava de seguranca: no maximo 1h por sessao
    * max_containers=1     -> nunca sobe mais de uma T4 por engano
- Mesmo assim: FECHE a aba e rode `modal app stop` ao terminar, para garantir.

MODELOS: ficam no Volume 'videos-virais-modelos', subpasta /models/comfyui, que o
ComfyUI usa como pasta de modelos. O epiCRealism e baixado para la UMA vez pela
funcao download_epicrealism (precisa do Secret CIVITAI_TOKEN no Modal).

COMANDOS:
  # baixar o epiCRealism para o Volume (uma vez; CPU, barato):
  modal run modal_app/comfyui.py::download_epicrealism

  # subir o ComfyUI interativo (abre uma URL web):
  modal serve modal_app/comfyui.py

  # desligar explicitamente ao terminar:
  modal app stop comfyui-aprendizado
"""

import subprocess

import modal

# --------------------------------------------------------------------------- #
VOLUME_NAME = "videos-virais-modelos"
# Dentro do Volume, uma pasta so para os modelos do ComfyUI (nao mistura com o Wan).
MODELS_ROOT = "/vol/comfyui"
GPU = "T4"

app = modal.App("comfyui-aprendizado")
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# Imagem: ComfyUI + dependencias. Clona o ComfyUI na propria imagem (build),
# assim nao reclona a cada container (mais rapido para subir).
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget")
    .run_commands(
        "git clone https://github.com/comfyanonymous/ComfyUI /root/ComfyUI",
        "pip install -r /root/ComfyUI/requirements.txt",
        # ComfyUI-Manager (instalar/gerenciar nodes pela UI)
        "git clone https://github.com/Comfy-Org/ComfyUI-Manager /root/ComfyUI/custom_nodes/comfyui-manager",
        "pip install -r /root/ComfyUI/custom_nodes/comfyui-manager/requirements.txt",
    )
    .pip_install("torch", "torchvision", "torchaudio")  # garante stack de GPU
)


# --------------------------------------------------------------------------- #
# Download do epiCRealism para o Volume (CPU, barato — roda uma vez)
# --------------------------------------------------------------------------- #
@app.function(
    image=image,
    volumes={"/vol": volume},
    timeout=60 * 30,
    secrets=[modal.Secret.from_name("civitai")],  # Secret com CIVITAI_TOKEN
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
# ComfyUI interativo (web). A T4 so sobe quando acessada e cai apos ociosidade.
# --------------------------------------------------------------------------- #
@app.function(
    image=image,
    gpu=GPU,
    volumes={"/vol": volume},
    timeout=3600,            # trava: no maximo 1h por sessao
    scaledown_window=60,     # cai 60s apos a ultima requisicao (para de cobrar)
    max_containers=1,        # nunca mais de uma T4
)
@modal.concurrent(max_inputs=100)  # permite varias requisicoes do navegador no mesmo container
@modal.web_server(8188, startup_timeout=120)
def ui():
    import os

    # Garante a estrutura de pastas de modelos no Volume e aponta o ComfyUI para la.
    for sub in ("checkpoints", "loras", "vae", "clip", "unet", "controlnet",
                "upscale_models", "embeddings"):
        os.makedirs(f"{MODELS_ROOT}/{sub}", exist_ok=True)

    # extra_model_paths.yaml: ComfyUI le os modelos do Volume.
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
    with open("/root/ComfyUI/extra_model_paths.yaml", "w") as f:
        f.write(yaml)

    # Sobe o ComfyUI escutando na porta 8188 (que o web_server expoe).
    cmd = "cd /root/ComfyUI && python main.py --listen 0.0.0.0 --port 8188"
    subprocess.Popen(cmd, shell=True)
