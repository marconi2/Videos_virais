#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kaggle_setup.py — Setup do ComfyUI no Kaggle (laboratorio de aprendizado).

ESTRATEGIA DE ARMAZENAMENTO (resolve o limite de ~20 GB do /kaggle/working):
- /kaggle/working  -> ~20 GB, apagado ao desligar. Aqui roda o ComfyUI.
- /kaggle/input/<dataset>  -> onde Datasets sao montados: PERSISTENTE, fora dos
  20 GB, somente-leitura, carrega instantaneo. Aqui ficam os MODELOS GRANDES.

Os modelos NAO sao copiados para o working (gastaria os 20 GB). Em vez disso,
o ComfyUI e apontado para o Dataset via extra_model_paths.yaml (read-only), e
uma pasta GRAVAVEL no working guarda modelos baixados na hora (sob demanda).

TOKENS: lidos dos SECRETS do Kaggle (Add-ons > Secrets), NAO colados em celula.
  Secrets esperados: HF_TOKEN, CIVITAI_TOKEN.

COMO USAR NO KAGGLE (uma celula):
    !wget -q https://raw.githubusercontent.com/marconi2/Videos_virais/main/kaggle_setup.py -O setup.py && python setup.py

Pre-requisitos no notebook: GPU T4 x2 + Internet On; Secrets HF_TOKEN e
CIVITAI_TOKEN criados; e (quando houver) o Dataset de modelos anexado.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #
COMFY = "/kaggle/working/ComfyUI"
CKPT_WORKING = COMFY + "/models/checkpoints"          # gravavel (download na hora)
CLOUDFLARED = "/kaggle/working/cloudflared"

# Nome do Dataset de modelos (ajuste se usar outro nome ao criar o Dataset).
# O caminho real dentro de /kaggle/input varia (ex.: /kaggle/input/comfyui-models/
# ou /kaggle/input/datasets/<user>/comfyui-models/comfyui-models/). Por isso o
# script DETECTA automaticamente a pasta que contem 'checkpoints' (ver
# detectar_dataset_base), em vez de depender de um caminho fixo.
DATASET_DIR = ""  # preenchido em runtime por detectar_dataset_base()


# --------------------------------------------------------------------------- #
# Tokens via Secrets do Kaggle (com fallback para variavel de ambiente)
# --------------------------------------------------------------------------- #
def ler_secret(nome: str) -> str:
    # 1) tenta o Secrets do Kaggle
    try:
        from kaggle_secrets import UserSecretsClient
        return UserSecretsClient().get_secret(nome)
    except Exception:
        pass
    # 2) fallback: variavel de ambiente (caso rode fora do Kaggle)
    return os.environ.get(nome, "")


HF_TOKEN = ler_secret("HF_TOKEN")
CIVITAI_TOKEN = ler_secret("CIVITAI_TOKEN")


def run(cmd, **kw):
    print(">>", cmd if isinstance(cmd, str) else " ".join(cmd))
    return subprocess.run(cmd, shell=isinstance(cmd, str), **kw)


# --------------------------------------------------------------------------- #
# Instalacao do ComfyUI e do Manager
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Custom nodes extras (fixos) — reinstalados a cada sessao, pois o working some.
# Para ADICIONAR um node: coloque a URL do repositorio git na lista CUSTOM_NODES.
# O setup faz git clone + instala requirements.txt + roda install.py (se houver).
# --------------------------------------------------------------------------- #
CUSTOM_NODES = [
    "https://github.com/ltdrdata/ComfyUI-Inspire-Pack",
    # adicione outros aqui, ex.:
    # "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
]


def instalar_custom_nodes():
    cn_dir = COMFY + "/custom_nodes"
    for url in CUSTOM_NODES:
        nome = url.rstrip("/").split("/")[-1]
        destino = os.path.join(cn_dir, nome)
        if os.path.exists(destino):
            print(f">> node ja existe: {nome}")
            continue
        print(f">> instalando node: {nome}")
        run(["git", "clone", url, destino], check=True)
        req = os.path.join(destino, "requirements.txt")
        if os.path.exists(req):
            run(["pip", "install", "-r", req], check=False)
        inst = os.path.join(destino, "install.py")
        if os.path.exists(inst):
            run(["python", inst], check=False)
        print(f">> node pronto: {nome}")


# --------------------------------------------------------------------------- #
# Apontar o ComfyUI para os modelos do Dataset (SEM copiar — read-only)
# --------------------------------------------------------------------------- #
def detectar_dataset_base():
    """Procura dentro de /kaggle/input a pasta que contem 'checkpoints'.

    O Kaggle monta o Dataset em caminhos que variam (com/sem subpastas extras),
    entao em vez de fixar o caminho, varremos /kaggle/input atras de uma pasta
    'checkpoints' e usamos o pai dela como base. Retorna o caminho base ou "".
    """
    raiz = "/kaggle/input"
    if not os.path.isdir(raiz):
        return ""
    for atual, dirs, _ in os.walk(raiz):
        if os.path.basename(atual) == "checkpoints":
            base = os.path.dirname(atual)
            print(f">> Dataset detectado automaticamente: {base}")
            return base
    return ""


def configurar_dataset():
    """Cria extra_model_paths.yaml apontando para o Dataset, se ele existir.

    O ComfyUI le modelos de VARIAS pastas: as do working (gravaveis, download na
    hora) E as listadas no extra_model_paths.yaml (o Dataset, read-only). Assim os
    modelos grandes ficam no Dataset (persistente, fora dos 20 GB) e aparecem
    normalmente nos nos Load Checkpoint.
    """
    global DATASET_DIR
    DATASET_DIR = detectar_dataset_base()
    if not DATASET_DIR:
        print(">> [info] Nenhum Dataset com 'checkpoints' encontrado em /kaggle/input.")
        print(">>        Anexe o Dataset de modelos ao notebook (+ Add Input).")
        return

    # Estrutura esperada DENTRO do Dataset: checkpoints/, loras/, vae/, etc.
    yaml = f"""kaggle_dataset:
    base_path: {DATASET_DIR}
    checkpoints: checkpoints
    loras: loras
    vae: vae
    clip: clip
    unet: unet
    controlnet: controlnet
    upscale_models: upscale_models
"""
    destino = COMFY + "/extra_model_paths.yaml"
    with open(destino, "w", encoding="utf-8") as f:
        f.write(yaml)
    print(f">> Dataset conectado via extra_model_paths.yaml")
    # lista o que tem no dataset (ajuda a conferir)
    ck = os.path.join(DATASET_DIR, "checkpoints")
    if os.path.isdir(ck):
        print(">> Modelos no Dataset (checkpoints):")
        for f in os.listdir(ck):
            print("    -", f)


# --------------------------------------------------------------------------- #
# Download sob demanda (para o WORKING — modelos pequenos / testes rapidos)
# --------------------------------------------------------------------------- #
def baixar_epicrealism_working():
    """Baixa o epiCRealism para o working SOMENTE se ele nao estiver no Dataset.

    Se o modelo ja veio no Dataset (detectado em configurar_dataset), nao baixa
    nada — o ComfyUI le direto do Dataset. So baixa no working como fallback.
    """
    nome = "epicrealism_naturalSinRC1VAE.safetensors"
    # ja esta no Dataset? entao nao precisa baixar
    if DATASET_DIR and os.path.exists(os.path.join(DATASET_DIR, "checkpoints", nome)):
        print(">> epiCRealism ja esta no Dataset — nao baixa no working")
        return
    destino = CKPT_WORKING + "/" + nome
    if os.path.exists(destino):
        print(">> epiCRealism ja existe no working")
        return
    if not CIVITAI_TOKEN:
        print(">> [PULADO] epiCRealism: Secret CIVITAI_TOKEN ausente e nao esta no Dataset.")
        return
    os.makedirs(CKPT_WORKING, exist_ok=True)
    url = "https://civitai.com/api/download/models/143906?token=" + CIVITAI_TOKEN
    print(">> Baixando epiCRealism (~2 GB) para o working...")
    run(["wget", "--content-disposition", url, "-O", destino], check=True)
    if os.path.exists(destino):
        print(">> epiCRealism:", round(os.path.getsize(destino) / 1024**3, 2), "GB")


# --------------------------------------------------------------------------- #
# Servidor + tunel
# --------------------------------------------------------------------------- #
def baixar_cloudflared():
    if not os.path.exists(CLOUDFLARED):
        run(["wget", "-q",
             "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
             "-O", CLOUDFLARED], check=True)
        run(["chmod", "+x", CLOUDFLARED], check=True)
        print(">> cloudflared pronto")
    return CLOUDFLARED


def subir_servidor_e_tunel(cf):
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
    comfy.wait()


def main():
    instalar_comfyui()
    instalar_manager()
    instalar_custom_nodes()     # nodes fixos (Inspire Pack etc.) — reinstala sempre
    configurar_dataset()        # aponta para o Dataset (modelos grandes), se anexado
    baixar_epicrealism_working()  # modelo leve para aprender agora
    cf = baixar_cloudflared()
    subir_servidor_e_tunel(cf)


if __name__ == "__main__":
    main()
