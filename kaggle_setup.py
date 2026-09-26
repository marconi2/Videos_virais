#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kaggle_setup.py — Setup completo do ComfyUI no Kaggle (laboratorio de aprendizado).

Instala ComfyUI + ComfyUI-Manager, baixa os modelos (Flux FP8 e epiCRealism),
sobe o servidor e abre o tunel cloudflared. Idempotente: se algo ja existe na
sessao, nao refaz.

COMO USAR NO KAGGLE (uma linha, sem copiar codigo longo):
    !wget -q https://raw.githubusercontent.com/<SEU_USUARIO>/<SEU_REPO>/main/kaggle_setup.py -O setup.py && python setup.py

Tokens: defina como variaveis de ambiente ANTES de rodar (celula separada, curta):
    import os
    os.environ["HF_TOKEN"] = "hf_..."          # token de leitura do HuggingFace
    os.environ["CIVITAI_TOKEN"] = "..."         # api key do Civitai (opcional)

Assim os tokens NAO ficam escritos no script publico do GitHub.
"""

import os
import re
import shutil
import subprocess
import threading
import time

COMFY = "/kaggle/working/ComfyUI"
CKPT_DIR = COMFY + "/models/checkpoints"

HF_TOKEN = os.environ.get("HF_TOKEN", "")
CIVITAI_TOKEN = os.environ.get("CIVITAI_TOKEN", "")


def run(cmd, **kw):
    """Roda um comando e mostra na tela; aceita lista ou string."""
    print(">>", cmd if isinstance(cmd, str) else " ".join(cmd))
    return subprocess.run(cmd, shell=isinstance(cmd, str), **kw)


def instalar_comfyui():
    if not os.path.exists(COMFY):
        run(["git", "clone", "https://github.com/comfyanonymous/ComfyUI", COMFY], check=True)
        run(["pip", "install", "-r", COMFY + "/requirements.txt"], check=True)
        print(">> ComfyUI instalado")
    else:
        print(">> ComfyUI ja existe")


def instalar_manager():
    mgr = COMFY + "/custom_nodes/comfyui-manager"
    if not os.path.exists(mgr):
        run(["git", "clone", "https://github.com/Comfy-Org/ComfyUI-Manager", mgr], check=True)
        run(["pip", "install", "-r", mgr + "/requirements.txt"], check=True)
        print(">> Manager instalado")
    else:
        print(">> Manager ja existe")


def baixar_flux():
    destino = CKPT_DIR + "/flux1-dev-fp8.safetensors"
    if os.path.exists(destino):
        print(">> Flux ja existe")
        return
    if not HF_TOKEN:
        print(">> [PULADO] Flux: defina HF_TOKEN para baixar.")
        return
    from huggingface_hub import hf_hub_download
    print(">> Baixando Flux FP8 (~17 GB)...")
    os.makedirs(CKPT_DIR, exist_ok=True)
    arq = hf_hub_download(repo_id="Comfy-Org/flux1-dev",
                          filename="flux1-dev-fp8.safetensors", token=HF_TOKEN)
    shutil.copy(arq, destino)
    print(">> Flux pronto:", round(os.path.getsize(destino) / 1024**3, 1), "GB")


def baixar_epicrealism():
    destino = CKPT_DIR + "/epicrealism.safetensors"
    if os.path.exists(destino):
        print(">> epiCRealism ja existe")
        return
    if not CIVITAI_TOKEN:
        print(">> [PULADO] epiCRealism: defina CIVITAI_TOKEN para baixar.")
        return
    os.makedirs(CKPT_DIR, exist_ok=True)
    url = "https://civitai.com/api/download/models/143906?token=" + CIVITAI_TOKEN
    print(">> Baixando epiCRealism...")
    run(["wget", "--content-disposition", url, "-O", destino], check=True)
    if os.path.exists(destino):
        print(">> epiCRealism:", round(os.path.getsize(destino) / 1024**3, 2), "GB")


def baixar_cloudflared():
    cf = "/kaggle/working/cloudflared"
    if not os.path.exists(cf):
        run(["wget", "-q",
             "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
             "-O", cf], check=True)
        run(["chmod", "+x", cf], check=True)
        print(">> cloudflared pronto")
    return cf


def subir_servidor_e_tunel(cf):
    # mata instancias antigas (evita 'Database is locked')
    run("pkill -f main.py")
    run("pkill -f cloudflared")
    time.sleep(3)

    os.chdir(COMFY)
    comfy = subprocess.Popen(["python", "main.py", "--listen", "127.0.0.1", "--port", "8188"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def _log():
        for l in comfy.stdout:
            print("[comfy]", l, end="")
            if "Starting server" in l:
                break
    threading.Thread(target=_log, daemon=True).start()
    print(">> Subindo ComfyUI (aguarde ~45s)...")
    time.sleep(45)

    tun = subprocess.Popen([cf, "tunnel", "--url", "http://127.0.0.1:8188"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for l in tun.stdout:
        print("[tunel]", l, end="")
        m = re.search(r"https://[-\w]+\.trycloudflare\.com", l)
        if m:
            print("\n\n>>> ABRA NO NAVEGADOR:", m.group(0), "\n")
            break
    # mantem o processo vivo
    comfy.wait()


def main():
    instalar_comfyui()
    instalar_manager()
    baixar_flux()
    baixar_epicrealism()
    cf = baixar_cloudflared()
    subir_servidor_e_tunel(cf)


if __name__ == "__main__":
    main()
