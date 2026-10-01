#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kaggle_setup.py — Setup completo do ComfyUI no Kaggle.

Instala:
- ComfyUI
- ComfyUI-Manager
- Flux FP8
- epiCRealism
- cloudflared

Também permite:
- baixar modelos do Civitai por link
- escolher a pasta do modelo
- instalar Custom Nodes do GitHub
- evitar downloads/clones repetidos na sessão

USO BÁSICO NO KAGGLE:
    !wget -q https://raw.githubusercontent.com/marconi2/Videos_virais/main/kaggle_setup.py -O setup.py && python setup.py

TOKENS (em uma célula separada):
    import os
    os.environ["HF_TOKEN"] = "hf_..."
    os.environ["CIVITAI_TOKEN"] = "..."

EXEMPLOS:
    # Civitai -> qualquer pasta do ComfyUI
    !python setup.py --civitai "https://civitai.com/models/143906" --pasta models/checkpoints --no-server

    # URL direta de outro site
    !python setup.py --download "https://servidor.com/model.safetensors" --pasta models/loras --no-server

    # Custom Node
    !python setup.py --node "https://github.com/autor/ComfyUI-Node.git"

    # Instalar somente a base, sem subir servidor:
    !python setup.py --no-server

PERSISTENCIA NO KAGGLE:
- Modelos, Custom Nodes, input e output ficam em:
    /kaggle/working/ComfyUI_Persistent/
- O ComfyUI usa symlinks para essas pastas.
- Para esses arquivos sobreviverem ao encerramento/reinício da sessão,
  ative no Kaggle: Settings > Persistence > Files.
- /kaggle/input é somente leitura, portanto nao usamos essa pasta como destino.
- A persistência do Kaggle é best-effort e possui limites; para bibliotecas
  muito grandes, um Dataset privado do Kaggle pode ser mais apropriado.
"""

import argparse
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import unquote

# Kaggle Interactive Notebook:
# habilite Settings > Persistence > Files para que /kaggle/working seja
# restaurado entre sessões. O Kaggle informa que a persistência de arquivos
# cobre os arquivos em /kaggle/working; /kaggle/input é somente leitura.
WORKING = "/kaggle/working"

# Mantemos o código do ComfyUI separado dos dados que queremos preservar.
COMFY = os.path.join(WORKING, "ComfyUI")
PERSIST_ROOT = os.path.join(WORKING, "ComfyUI_Persistent")

PERSIST_MODELS = os.path.join(PERSIST_ROOT, "models")
PERSIST_NODES = os.path.join(PERSIST_ROOT, "custom_nodes")
PERSIST_INPUT = os.path.join(PERSIST_ROOT, "input")
PERSIST_OUTPUT = os.path.join(PERSIST_ROOT, "output")

MODELS = os.path.join(COMFY, "models")
CKPT_DIR = os.path.join(MODELS, "checkpoints")
CUSTOM_NODES = os.path.join(COMFY, "custom_nodes")
INPUT_DIR = os.path.join(COMFY, "input")
OUTPUT_DIR = os.path.join(COMFY, "output")

HF_TOKEN = os.environ.get("HF_TOKEN", "")
CIVITAI_TOKEN = os.environ.get("CIVITAI_TOKEN", "")


def preparar_armazenamento_persistente():
    """
    Cria uma área de dados em /kaggle/working/ComfyUI_Persistent e liga
    as pastas usadas pelo ComfyUI a essa área por symlink.

    IMPORTANTE:
    No Kaggle, isso só sobrevive a uma nova sessão se a opção
    Settings > Persistence > Files estiver habilitada para o notebook.
    """
    os.makedirs(PERSIST_ROOT, exist_ok=True)

    pastas = {
        PERSIST_MODELS: MODELS,
        PERSIST_NODES: CUSTOM_NODES,
        PERSIST_INPUT: INPUT_DIR,
        PERSIST_OUTPUT: OUTPUT_DIR,
    }

    for persistente, destino in pastas.items():
        os.makedirs(persistente, exist_ok=True)

        if os.path.islink(destino):
            atual = os.path.realpath(destino)
            if atual == os.path.realpath(persistente):
                continue
            os.unlink(destino)

        elif os.path.exists(destino):
            # Se já houver dados locais do ComfyUI, preserva-os migrando
            # para a área persistente antes de criar o link.
            if os.path.isdir(destino):
                for item in os.listdir(destino):
                    origem_item = os.path.join(destino, item)
                    destino_item = os.path.join(persistente, item)
                    if os.path.exists(destino_item):
                        continue
                    shutil.move(origem_item, destino_item)
                os.rmdir(destino)
            else:
                os.remove(destino)

        os.symlink(persistente, destino)

    print(">> Armazenamento persistente preparado:")
    print(">> Modelos :", PERSIST_MODELS)
    print(">> Nodes   :", PERSIST_NODES)
    print(">> Input   :", PERSIST_INPUT)
    print(">> Output  :", PERSIST_OUTPUT)


def run(cmd, **kw):
    """Executa comando e mostra na tela."""
    print(">>", cmd if isinstance(cmd, str) else " ".join(map(str, cmd)))
    return subprocess.run(cmd, shell=isinstance(cmd, str), **kw)


def instalar_comfyui():
    if not os.path.exists(COMFY):
        run(
            ["git", "clone", "https://github.com/comfyanonymous/ComfyUI", COMFY],
            check=True,
        )
        run(["pip", "install", "-r", os.path.join(COMFY, "requirements.txt")], check=True)
        print(">> ComfyUI instalado")
    else:
        print(">> ComfyUI ja existe")


def instalar_manager():
    mgr = os.path.join(CUSTOM_NODES, "comfyui-manager")

    if not os.path.exists(mgr):
        os.makedirs(CUSTOM_NODES, exist_ok=True)
        run(
            ["git", "clone", "https://github.com/Comfy-Org/ComfyUI-Manager", mgr],
            check=True,
        )

        req = os.path.join(mgr, "requirements.txt")
        if os.path.exists(req):
            run(["pip", "install", "-r", req], check=True)

        print(">> Manager instalado")
    else:
        print(">> Manager ja existe")


def baixar_flux():
    destino = os.path.join(CKPT_DIR, "flux1-dev-fp8.safetensors")

    if os.path.exists(destino):
        print(">> Flux ja existe")
        return

    if not HF_TOKEN:
        print(">> [PULADO] Flux: defina HF_TOKEN para baixar.")
        return

    from huggingface_hub import hf_hub_download

    print(">> Baixando Flux FP8 (~17 GB)...")
    os.makedirs(CKPT_DIR, exist_ok=True)

    arq = hf_hub_download(
        repo_id="Comfy-Org/flux1-dev",
        filename="flux1-dev-fp8.safetensors",
        token=HF_TOKEN,
    )

    shutil.copy2(arq, destino)

    print(
        ">> Flux pronto:",
        round(os.path.getsize(destino) / 1024**3, 1),
        "GB",
    )


def baixar_epicrealism():
    destino = os.path.join(
        CKPT_DIR,
        "epicrealism_naturalSinRC1VAE.safetensors",
    )

    if os.path.exists(destino):
        print(">> epiCRealism ja existe")
        return

    if not CIVITAI_TOKEN:
        print(">> [PULADO] epiCRealism: defina CIVITAI_TOKEN para baixar.")
        return

    os.makedirs(CKPT_DIR, exist_ok=True)

    url = (
        "https://civitai.com/api/download/models/"
        "143906?token=" + CIVITAI_TOKEN
    )

    print(">> Baixando epiCRealism...")

    run(
        [
            "wget",
            "--content-disposition",
            url,
            "-O",
            destino,
        ],
        check=True,
    )

    if os.path.exists(destino):
        print(
            ">> epiCRealism:",
            round(os.path.getsize(destino) / 1024**3, 2),
            "GB",
        )


def pasta_modelo(tipo):
    """
    Mapeia o tipo informado para a pasta padrão do ComfyUI.
    """
    mapa = {
        "checkpoint": CKPT_DIR,
        "checkpoints": CKPT_DIR,

        "lora": os.path.join(MODELS, "loras"),
        "loras": os.path.join(MODELS, "loras"),

        "vae": os.path.join(MODELS, "vae"),

        "controlnet": os.path.join(MODELS, "controlnet"),

        "clip": os.path.join(MODELS, "clip"),
        "text_encoder": os.path.join(MODELS, "text_encoders"),
        "text_encoders": os.path.join(MODELS, "text_encoders"),

        "diffusion": os.path.join(MODELS, "diffusion_models"),
        "diffusion_model": os.path.join(MODELS, "diffusion_models"),
        "diffusion_models": os.path.join(MODELS, "diffusion_models"),

        "unet": os.path.join(MODELS, "diffusion_models"),

        "upscale": os.path.join(MODELS, "upscale_models"),
        "upscale_model": os.path.join(MODELS, "upscale_models"),
        "upscale_models": os.path.join(MODELS, "upscale_models"),

        "embeddings": os.path.join(MODELS, "embeddings"),

        "style_models": os.path.join(MODELS, "style_models"),
    }

    if tipo not in mapa:
        raise ValueError(
            f"Tipo '{tipo}' nao reconhecido. "
            f"Use: {', '.join(sorted(mapa.keys()))}"
        )

    return mapa[tipo]


def nome_arquivo_url(url):
    """Tenta obter um nome de arquivo a partir da URL."""
    try:
        result = subprocess.run(
            ["curl", "-L", "-s", "-D", "-", "-o", "/dev/null", url],
            capture_output=True,
            text=True,
            check=True,
        )
        headers = result.stdout

        padroes = [
            r"filename\*\s*=\s*UTF-8''([^;\r\n]+)",
            r'filename\s*=\s*"([^"]+)"',
            r"filename\s*=\s*([^;\r\n]+)",
        ]

        for padrao in padroes:
            match = re.search(padrao, headers, re.IGNORECASE)
            if match:
                nome = unquote(match.group(1).strip().strip('"'))
                nome = os.path.basename(nome)
                if nome:
                    return nome
    except Exception as e:
        print(">> Aviso: nao foi possivel descobrir o nome do arquivo:", e)

    # Fallback para o último trecho da URL
    trecho = url.split("?")[0].rstrip("/").split("/")[-1]
    return os.path.basename(unquote(trecho)) or "download.bin"


def normalizar_pasta(pasta):
    """
    Converte uma pasta informada pelo usuário em um caminho seguro dentro do
    /kaggle/working/ComfyUI.

    Exemplos:
      models/checkpoints
      models/loras
      input
      output
    """
    pasta = pasta.strip().replace("\\", "/").lstrip("/")

    if not pasta:
        raise ValueError("A pasta nao pode estar vazia.")

    destino = os.path.abspath(os.path.join(COMFY, pasta))
    raiz = os.path.abspath(COMFY)

    if destino != raiz and not destino.startswith(raiz + os.sep):
        raise ValueError("A pasta deve ficar dentro de /kaggle/working/ComfyUI.")

    return destino


def baixar_url(url, pasta="models/checkpoints", nome=None):
    """
    Baixa qualquer URL que forneça um arquivo diretamente.

    Exemplo:
      baixar_url(
          "https://servidor.com/model.safetensors",
          "models/checkpoints"
      )

    O arquivo é salvo dentro do ComfyUI na pasta informada.
    """
    if not url.startswith(("http://", "https://")):
        print(">> [ERRO] A URL deve começar com http:// ou https://")
        return None

    try:
        destino_dir = normalizar_pasta(pasta)
    except ValueError as e:
        print(">> [ERRO]", e)
        return None

    os.makedirs(destino_dir, exist_ok=True)

    if not nome:
        nome = nome_arquivo_url(url)

    nome = os.path.basename(nome)
    destino = os.path.join(destino_dir, nome)

    if os.path.exists(destino):
        tamanho = os.path.getsize(destino) / 1024**3
        print(f">> Arquivo ja existe: {destino}")
        print(f">> Tamanho: {tamanho:.2f} GB")
        return destino

    print(f">> URL: {url}")
    print(f">> Destino: {destino}")
    print(">> Iniciando download...")

    try:
        run(
            [
                "wget",
                "--content-disposition",
                "--show-progress",
                url,
                "-O",
                destino,
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        print(">> [ERRO] Falha no download.")
        if os.path.exists(destino):
            try:
                os.remove(destino)
            except OSError:
                pass
        return None

    if not os.path.exists(destino):
        print(">> [ERRO] Arquivo nao encontrado apos o download.")
        return None

    tamanho = os.path.getsize(destino) / 1024**3
    print(f">> Download concluido: {destino}")
    print(f">> Tamanho: {tamanho:.2f} GB")
    return destino


def baixar_civitai(link, pasta="models/checkpoints"):
    """
    Baixa um modelo do Civitai usando o link da pagina do modelo.

    O link pode ser, por exemplo:
      https://civitai.com/models/143906

    O modelo é salvo na pasta informada dentro do ComfyUI.
    """
    if not CIVITAI_TOKEN:
        print(">> [ERRO] CIVITAI_TOKEN nao definido.")
        return None

    match = re.search(r"civitai\.com/models/(\d+)", link)
    if not match:
        print(">> [ERRO] Link do Civitai invalido.")
        print(">> Exemplo: https://civitai.com/models/143906")
        return None

    model_id = match.group(1)

    url = (
        f"https://civitai.com/api/download/models/"
        f"{model_id}?token={CIVITAI_TOKEN}"
    )

    print(f">> Civitai model ID: {model_id}")
    return baixar_url(url, pasta)



def nome_node_do_github(url):
    """
    Obtém um nome simples para o repositório GitHub.
    """
    url_limpa = url.rstrip("/").rstrip(".git")
    nome = url_limpa.split("/")[-1]

    if not nome:
        raise ValueError("Nao foi possivel identificar o nome do node.")

    return nome


def instalar_node(url):
    """
    Clona um Custom Node do GitHub para ComfyUI/custom_nodes.
    Se já existir, não clona novamente.
    Se houver requirements.txt, instala as dependências.
    """
    os.makedirs(CUSTOM_NODES, exist_ok=True)

    nome = nome_node_do_github(url)
    destino = os.path.join(CUSTOM_NODES, nome)

    if os.path.exists(destino):
        print(f">> Custom Node ja existe: {nome}")

        req = os.path.join(destino, "requirements.txt")
        if os.path.exists(req):
            print(f">> Verificando requirements de {nome}...")
            run(["pip", "install", "-r", req], check=True)

        return destino

    print(f">> Instalando Custom Node: {nome}")
    print(f">> URL: {url}")

    run(
        ["git", "clone", url, destino],
        check=True,
    )

    req = os.path.join(destino, "requirements.txt")

    if os.path.exists(req):
        print(f">> Instalando requirements de {nome}...")
        run(["pip", "install", "-r", req], check=True)

    print(f">> Custom Node pronto: {destino}")

    return destino


def baixar_cloudflared():
    cf = "/kaggle/working/cloudflared"

    if not os.path.exists(cf):
        run(
            [
                "wget",
                "-q",
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                "-O",
                cf,
            ],
            check=True,
        )

        run(["chmod", "+x", cf], check=True)
        print(">> cloudflared pronto")
    else:
        print(">> cloudflared ja existe")

    return cf


def subir_servidor_e_tunel(cf):
    # Mata instancias antigas para evitar conflitos.
    run("pkill -f main.py")
    run("pkill -f cloudflared")
    time.sleep(3)

    os.chdir(COMFY)

    comfy = subprocess.Popen(
        [
            "python",
            "main.py",
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def _log():
        for linha in comfy.stdout:
            print("[comfy]", linha, end="")

    threading.Thread(target=_log, daemon=True).start()

    print(">> Subindo ComfyUI (aguarde ~45s)...")
    time.sleep(45)

    tun = subprocess.Popen(
        [
            cf,
            "tunnel",
            "--url",
            "http://127.0.0.1:8188",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    for linha in tun.stdout:
        print("[tunel]", linha, end="")

        match = re.search(
            r"https://[-\w]+\.trycloudflare\.com",
            linha,
        )

        if match:
            print("\n\n>>> ABRA NO NAVEGADOR:", match.group(0), "\n")
            break

    # Mantém o processo principal vivo.
    comfy.wait()


def argumentos():
    parser = argparse.ArgumentParser(
        description="Setup/gerenciador do ComfyUI no Kaggle."
    )

    parser.add_argument(
        "--download",
        help="URL direta de download. Para Civitai, prefira --civitai.",
    )

    parser.add_argument(
        "--civitai",
        help="Link da pagina do modelo no Civitai.",
    )

    parser.add_argument(
        "--pasta",
        default="models/checkpoints",
        help="Pasta relativa dentro de ComfyUI. Ex.: models/loras, input, output.",
    )

    parser.add_argument(
        "--nome",
        default=None,
        help="Nome opcional do arquivo baixado.",
    )


    parser.add_argument(
        "--node",
        help="URL do repositorio GitHub de um Custom Node.",
    )

    parser.add_argument(
        "--no-server",
        action="store_true",
        help="Nao sobe o ComfyUI nem o Cloudflare Tunnel.",
    )

    parser.add_argument(
        "--skip-default-models",
        action="store_true",
        help="Nao baixa Flux e epiCRealism.",
    )

    return parser.parse_args()


def main():
    args = argumentos()

    # Primeiro garante que a estrutura base do ComfyUI exista.
    instalar_comfyui()

    # Depois conecta models/custom_nodes/input/output à área persistente.
    preparar_armazenamento_persistente()

    instalar_manager()

    if not args.skip_default_models:
        baixar_flux()
        baixar_epicrealism()

    # Download direto do Civitai.
    if args.civitai:
        baixar_civitai(args.civitai, args.pasta)

    # Download de qualquer URL direta.
    elif args.download:
        baixar_url(args.download, args.pasta, args.nome)

    # Instalação de Custom Node solicitado pelo usuário.
    if args.node:
        instalar_node(args.node)

    if args.no_server:
        print(">> --no-server: servidor nao sera iniciado.")
        return

    cf = baixar_cloudflared()
    subir_servidor_e_tunel(cf)


if __name__ == "__main__":
    main()
