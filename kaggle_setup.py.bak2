#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# ============================================================
# CONFIGURAÇÃO
# ============================================================

WORKING = Path("/kaggle/working")
COMFY = WORKING / "ComfyUI"

# Armazenamento persistente do Kaggle (Variables & Files)
PERSIST_ROOT = WORKING / "ComfyUI_Persistent"
PERSIST_MODELS = PERSIST_ROOT / "models"
PERSIST_NODES = PERSIST_ROOT / "custom_nodes"
PERSIST_INPUT = PERSIST_ROOT / "input"
PERSIST_OUTPUT = PERSIST_ROOT / "output"

MODELS = COMFY / "models"
CUSTOM_NODES = COMFY / "custom_nodes"
INPUT_DIR = COMFY / "input"
OUTPUT_DIR = COMFY / "output"
CKPT_DIR = MODELS / "checkpoints"

MANAGER_DIR = CUSTOM_NODES / "ComfyUI-Manager"
CLOUDFLARED = WORKING / "cloudflared"

COMFY_REPO = "https://github.com/comfyanonymous/ComfyUI.git"
MANAGER_REPO = "https://github.com/ltdrdata/ComfyUI-Manager.git"

COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188


# ============================================================
# UTILITÁRIOS
# ============================================================

def run(cmd, cwd=None, check=True, capture=False):
    """Executa um comando e mostra o comando na tela."""
    print(">>", " ".join(map(str, cmd)))
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=capture,
    )


def pip_install(*packages):
    """Instala pacotes usando o mesmo Python do notebook."""
    run([sys.executable, "-m", "pip", "install", *packages])


def safe_mkdir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def caminho_dentro_do_comfy(relativo):
    """
    Converte uma pasta relativa em caminho absoluto dentro do ComfyUI.
    Impede que --pasta escape de /kaggle/working/ComfyUI.
    """
    relativo = (relativo or "").strip().lstrip("/\\")
    destino = (COMFY / relativo).resolve()
    raiz = COMFY.resolve()

    if destino != raiz and raiz not in destino.parents:
        raise ValueError(f"Pasta inválida: {relativo}")

    return destino


def nome_a_partir_da_url(url):
    nome = Path(urlparse(url).path).name
    return nome or "download.bin"


def arquivo_tem_conteudo(path):
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


# ============================================================
# COMFYUI
# ============================================================

def instalar_comfyui():
    """
    Clona o ComfyUI se necessário e SEMPRE reinstala as dependências
    declaradas pelo próprio requirements.txt.

    Depois verifica comfy_aimdo. Se estiver faltando, instala.
    """

    if not COMFY.exists():
        print(">> ComfyUI não existe. Clonando...")
        run(["git", "clone", COMFY_REPO, COMFY])
    else:
        print(">> ComfyUI já existe")

    requirements = COMFY / "requirements.txt"

    if requirements.exists():
        print(">> Instalando/reinstalando dependências do ComfyUI...")
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            requirements,
        ])
    else:
        print("!! requirements.txt não encontrado:", requirements)

    garantir_comfy_aimdo()


def garantir_comfy_aimdo():
    """
    Não força upgrade desnecessário.
    Primeiro tenta importar. Se faltar, instala o pacote.
    """

    try:
        import comfy_aimdo  # noqa: F401
        print(">> comfy-aimdo já está instalado")
        return
    except ImportError:
        pass

    print(">> comfy-aimdo ausente. Instalando...")
    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "comfy-aimdo",
    ])

    try:
        import comfy_aimdo  # noqa: F401
        print(">> comfy-aimdo instalado com sucesso")
    except ImportError as e:
        raise RuntimeError(
            "O pacote comfy-aimdo foi instalado, mas ainda não pode ser importado."
        ) from e


# ============================================================
# ARMAZENAMENTO PERSISTENTE
# ============================================================

def migrar_conteudo(origem, destino):
    """
    Copia o conteúdo existente para o armazenamento persistente,
    sem apagar arquivos já existentes.
    """
    origem = Path(origem)
    destino = Path(destino)

    if not origem.exists() or origem.is_symlink():
        return

    safe_mkdir(destino)

    for item in origem.iterdir():
        alvo = destino / item.name

        if alvo.exists():
            continue

        print(f">> Migrando: {item} -> {alvo}")
        shutil.move(str(item), str(alvo))


def substituir_por_symlink(origem, destino):
    """
    Faz origem apontar para destino através de symlink.
    """
    origem = Path(origem)
    destino = Path(destino)

    if origem.is_symlink():
        try:
            atual = origem.resolve()
        except OSError:
            atual = None

        if atual == destino.resolve():
            return

        origem.unlink()

    elif origem.exists():
        if origem.is_dir():
            # Segurança: conteúdo já foi migrado antes.
            if any(origem.iterdir()):
                migrar_conteudo(origem, destino)
            shutil.rmtree(origem)
        else:
            origem.unlink()

    origem.parent.mkdir(parents=True, exist_ok=True)
    origem.symlink_to(destino, target_is_directory=True)


def preparar_armazenamento_persistente():
    """
    Mantém modelos, custom_nodes, input e output em
    /kaggle/working/ComfyUI_Persistent.
    """

    for pasta in [
        PERSIST_ROOT,
        PERSIST_MODELS,
        PERSIST_NODES,
        PERSIST_INPUT,
        PERSIST_OUTPUT,
    ]:
        safe_mkdir(pasta)

    # Migra conteúdos antigos antes de transformar em symlink.
    migrar_conteudo(MODELS, PERSIST_MODELS)
    migrar_conteudo(CUSTOM_NODES, PERSIST_NODES)
    migrar_conteudo(INPUT_DIR, PERSIST_INPUT)
    migrar_conteudo(OUTPUT_DIR, PERSIST_OUTPUT)

    substituir_por_symlink(MODELS, PERSIST_MODELS)
    substituir_por_symlink(CUSTOM_NODES, PERSIST_NODES)
    substituir_por_symlink(INPUT_DIR, PERSIST_INPUT)
    substituir_por_symlink(OUTPUT_DIR, PERSIST_OUTPUT)

    print(">> Armazenamento persistente preparado:")
    print(">> Modelos :", PERSIST_MODELS)
    print(">> Nodes   :", PERSIST_NODES)
    print(">> Input   :", PERSIST_INPUT)
    print(">> Output  :", PERSIST_OUTPUT)


# ============================================================
# COMFYUI MANAGER
# ============================================================

def instalar_manager():
    safe_mkdir(CUSTOM_NODES)

    if MANAGER_DIR.exists():
        print(">> Manager já existe")
        return

    print(">> Instalando ComfyUI-Manager...")
    run(["git", "clone", MANAGER_REPO, MANAGER_DIR])

    requirements = MANAGER_DIR / "requirements.txt"
    if requirements.exists():
        print(">> Instalando dependências do Manager...")
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            requirements,
        ])


# ============================================================
# DOWNLOADS
# ============================================================

def baixar_url(url, pasta, nome=None):
    """
    Baixa qualquer URL direta para uma pasta dentro do ComfyUI.

    Exemplo:
      --download https://site/model.safetensors
      --pasta models/loras
    """

    destino_dir = caminho_dentro_do_comfy(pasta)
    safe_mkdir(destino_dir)

    if not nome:
        nome = nome_a_partir_da_url(url)

    destino = destino_dir / nome

    if arquivo_tem_conteudo(destino):
        print(f">> Arquivo já existe. Não baixando novamente: {destino}")
        return destino

    print(f">> Baixando:")
    print(f">> URL    : {url}")
    print(f">> Destino: {destino}")

    try:
        urllib.request.urlretrieve(url, destino)
    except Exception:
        # Remove arquivo parcial para permitir nova tentativa.
        try:
            destino.unlink()
        except OSError:
            pass
        raise

    print(">> Download concluído:", destino)
    return destino


def extrair_model_id_civitai(link):
    """
    Aceita:
      https://civitai.com/models/123456
      https://www.civitai.com/models/123456/slug
    """
    match = re.search(r"civitai\.com/models/(\d+)", link)
    if not match:
        raise ValueError(
            "Não foi possível encontrar o ID do modelo Civitai no link."
        )

    return match.group(1)


def obter_nome_civitai(response):
    """
    Tenta descobrir o nome original pelo Content-Disposition.
    """
    cd = response.headers.get("Content-Disposition", "")

    match = re.search(
        r'filename\*=UTF-8\'\'([^;]+)',
        cd,
        flags=re.IGNORECASE,
    )
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1)).strip('"')

    match = re.search(
        r'filename="?([^";]+)"?',
        cd,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    return None


def baixar_civitai(link, pasta, nome=None):
    """
    Baixa um modelo do Civitai usando CIVITAI_TOKEN.

    A URL pública do modelo é convertida para:
      https://civitai.com/api/download/models/<ID>?token=<TOKEN>
    """

    token = os.environ.get("CIVITAI_TOKEN", "").strip()

    if not token:
        raise RuntimeError(
            "CIVITAI_TOKEN não foi configurado no ambiente do Kaggle."
        )

    model_id = extrair_model_id_civitai(link)
    url = f"https://civitai.com/api/download/models/{model_id}?token={token}"

    destino_dir = caminho_dentro_do_comfy(pasta)
    safe_mkdir(destino_dir)

    # Se o usuário passou nome explícito, podemos testar diretamente.
    if nome:
        destino = destino_dir / nome
        if arquivo_tem_conteudo(destino):
            print(f">> Arquivo já existe: {destino}")
            return destino

    print(f">> Baixando modelo Civitai ID {model_id}...")
    print(f">> Destino: {destino_dir}")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    with urllib.request.urlopen(request) as response:
        nome_header = obter_nome_civitai(response)
        nome_final = nome or nome_header or f"civitai_model_{model_id}.bin"
        destino = destino_dir / nome_final

        if arquivo_tem_conteudo(destino):
            print(f">> Arquivo já existe: {destino}")
            return destino

        total = response.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else None

        temporario = destino.with_suffix(destino.suffix + ".part")

        try:
            with open(temporario, "wb") as f:
                baixado = 0

                while True:
                    bloco = response.read(1024 * 1024)
                    if not bloco:
                        break

                    f.write(bloco)
                    baixado += len(bloco)

                    if total:
                        pct = baixado * 100 / total
                        print(
                            f"\r>> {pct:6.2f}% "
                            f"({baixado / 1024 / 1024:.1f} MB / "
                            f"{total / 1024 / 1024:.1f} MB)",
                            end="",
                            flush=True,
                        )

            if total:
                print()

            temporario.replace(destino)

        except Exception:
            try:
                temporario.unlink()
            except OSError:
                pass
            raise

    print(">> Download Civitai concluído:", destino)
    return destino


# ============================================================
# CUSTOM NODES
# ============================================================

def nome_repo_git(url):
    url_limpa = url.rstrip("/")
    nome = url_limpa.split("/")[-1]

    if nome.endswith(".git"):
        nome = nome[:-4]

    if not nome:
        raise ValueError("Não foi possível identificar o nome do repositório.")

    return nome


def instalar_node(url):
    safe_mkdir(CUSTOM_NODES)

    repo_name = nome_repo_git(url)
    destino = CUSTOM_NODES / repo_name

    if destino.exists():
        print(f">> Custom Node já existe: {destino}")
        return destino

    print(f">> Instalando Custom Node: {url}")
    run(["git", "clone", url, destino])

    requirements = destino / "requirements.txt"

    if requirements.exists():
        print(f">> Instalando dependências de {repo_name}...")
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            requirements,
        ])

    print(">> Custom Node instalado:", destino)
    return destino


# ============================================================
# MODELOS PADRÃO
# ============================================================

def instalar_modelos_padrao():
    """
    Mantém a lógica dos modelos padrão usados no projeto.
    Se os tokens não estiverem configurados, simplesmente pula.
    """

    hf_token = os.environ.get("HF_TOKEN", "").strip()
    civitai_token = os.environ.get("CIVITAI_TOKEN", "").strip()

    # --------------------------------------------------------
    # Flux FP8 - exemplo
    # --------------------------------------------------------
    # Ajuste estas URLs conforme os modelos que você realmente
    # quiser manter como padrão no seu repositório.
    #
    # O bloco abaixo só tenta baixar quando uma URL foi definida.
    # --------------------------------------------------------

    flux_url = os.environ.get("DEFAULT_FLUX_URL", "").strip()

    if flux_url:
        try:
            baixar_url(
                flux_url,
                "models/diffusion_models",
            )
        except Exception as e:
            print("!! Falha ao baixar Flux padrão:", e)
    else:
        print(">> Flux padrão: nenhuma URL DEFAULT_FLUX_URL configurada")

    # --------------------------------------------------------
    # epiCRealism / Civitai
    # --------------------------------------------------------

    epic_link = os.environ.get("DEFAULT_EPICREALISM_CIVITAI", "").strip()

    if epic_link and civitai_token:
        try:
            baixar_civitai(
                epic_link,
                "models/checkpoints",
            )
        except Exception as e:
            print("!! Falha ao baixar epiCRealism padrão:", e)
    elif not epic_link:
        print(
            ">> epiCRealism padrão: nenhuma URL "
            "DEFAULT_EPICREALISM_CIVITAI configurada"
        )
    else:
        print(">> CIVITAI_TOKEN ausente; epiCRealism padrão ignorado")


# ============================================================
# CLOUDFLARED
# ============================================================

def baixar_cloudflared():
    """
    Baixa cloudflared se não existir.

    IMPORTANTE:
    O chmod +x é aplicado SEMPRE, inclusive quando o arquivo
    já existe. Isso corrige o PermissionError causado quando
    o arquivo persistente perde a permissão de execução.
    """

    url = (
        "https://github.com/cloudflare/cloudflared/releases/latest/"
        "download/cloudflared-linux-amd64"
    )

    if CLOUDFLARED.exists():
        print(">> cloudflared já existe")
    else:
        print(">> Baixando cloudflared...")
        urllib.request.urlretrieve(url, CLOUDFLARED)
        print(">> Download do cloudflared concluído")

    # Sempre corrige a permissão.
    print(">> Aplicando chmod +x no cloudflared...")
    os.chmod(CLOUDFLARED, 0o755)

    if not os.access(CLOUDFLARED, os.X_OK):
        raise PermissionError(
            f"cloudflared existe, mas continua sem permissão de execução: "
            f"{CLOUDFLARED}"
        )

    print(">> cloudflared executável:", CLOUDFLARED)


# ============================================================
# SERVIDOR + CLOUDFLARE TUNNEL
# ============================================================

def matar_processos_antigos():
    print(">> Encerrando processos antigos...")

    subprocess.run(
        ["pkill", "-f", "main.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    subprocess.run(
        ["pkill", "-f", "cloudflared"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def subir_servidor_e_tunel():
    baixar_cloudflared()
    matar_processos_antigos()

    print(">> Subindo ComfyUI (aguarde o servidor iniciar)...")

    log_file = WORKING / "comfyui.log"

    with open(log_file, "w", encoding="utf-8") as log:
        comfy_process = subprocess.Popen(
            [
                sys.executable,
                str(COMFY / "main.py"),
                "--listen",
                COMFY_HOST,
                "--port",
                str(COMFY_PORT),
            ],
            cwd=str(COMFY),
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    # Não espera cegamente 45 segundos.
    # Verifica se o processo continua vivo.
    iniciado = False

    for _ in range(90):
        if comfy_process.poll() is not None:
            print("!! ComfyUI encerrou antes de iniciar.")
            print("!! Últimas linhas do log:")
            try:
                texto = log_file.read_text(encoding="utf-8", errors="replace")
                print("\n".join(texto.splitlines()[-40:]))
            except Exception:
                pass

            raise RuntimeError(
                f"ComfyUI encerrou com código {comfy_process.returncode}. "
                f"Veja o log em {log_file}"
            )

        # Verificação simples da porta.
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)

        try:
            sock.connect((COMFY_HOST, COMFY_PORT))
            iniciado = True
            break
        except OSError:
            time.sleep(1)
        finally:
            sock.close()

    if not iniciado:
        print("!! ComfyUI ainda não abriu a porta após 90 segundos.")
        print(f"!! Log: {log_file}")
        raise RuntimeError(
            "ComfyUI não iniciou dentro do tempo esperado."
        )

    print(f">> ComfyUI rodando em http://{COMFY_HOST}:{COMFY_PORT}")

    print(">> Iniciando Cloudflare Tunnel...")

    tunnel = subprocess.Popen(
        [
            str(CLOUDFLARED),
            "tunnel",
            "--url",
            f"http://{COMFY_HOST}:{COMFY_PORT}",
            "--no-autoupdate",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    print("\n==============================")
    print("   CLOUDFLARE TUNNEL")
    print("==============================")

    url_encontrada = False
    inicio = time.time()

    while time.time() - inicio < 30:
        linha = tunnel.stdout.readline()

        if not linha:
            if tunnel.poll() is not None:
                break
            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            print("[cloudflared]", linha)

        match = re.search(
            r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com",
            linha,
        )

        if match:
            print("\n==========================================")
            print("COMFYUI ONLINE:")
            print(match.group(0))
            print("==========================================\n")
            url_encontrada = True
            break

    if not url_encontrada:
        print(
            "\n!! URL do Cloudflare não apareceu automaticamente."
        )
        print(
            f"!! Processo cloudflared PID: {tunnel.pid}"
        )
        print(
            "!! O túnel pode ainda estar inicializando."
        )


# ============================================================
# ARGUMENTOS
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Setup completo do ComfyUI para Kaggle."
    )

    parser.add_argument(
        "--repair",
        action="store_true",
        help=(
            "Reinstala/verifica dependências, corrige comfy-aimdo "
            "e corrige permissão do cloudflared sem iniciar servidor."
        ),
    )

    parser.add_argument(
        "--civitai",
        help="Link de uma página de modelo do Civitai.",
    )

    parser.add_argument(
        "--download",
        help="URL direta de um arquivo/modelo.",
    )

    parser.add_argument(
        "--pasta",
        help=(
            "Pasta destino relativa ao ComfyUI. "
            "Ex.: models/checkpoints"
        ),
    )

    parser.add_argument(
        "--nome",
        help="Nome opcional para o arquivo baixado.",
    )

    parser.add_argument(
        "--node",
        help="URL GitHub de um Custom Node.",
    )

    parser.add_argument(
        "--no-server",
        action="store_true",
        help="Não iniciar ComfyUI nem Cloudflare Tunnel.",
    )

    parser.add_argument(
        "--skip-default-models",
        action="store_true",
        help="Não executar downloads de modelos padrão.",
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_args()

    print("\n==========================================")
    print(" COMFYUI KAGGLE SETUP")
    print("==========================================\n")

    # 1. ComfyUI + dependências
    instalar_comfyui()

    # 2. Persistência
    preparar_armazenamento_persistente()

    # 3. Manager
    instalar_manager()

    # 4. Modo reparo
    if args.repair:
        print("\n>> Modo --repair")
        baixar_cloudflared()
        print(">> Reparo concluído.")
        print(">> O servidor NÃO foi iniciado.")
        return

    # 5. Modelos padrão
    if not args.skip_default_models:
        instalar_modelos_padrao()

    # 6. Download Civitai
    if args.civitai:
        if not args.pasta:
            raise ValueError(
                "--civitai exige --pasta."
            )

        baixar_civitai(
            args.civitai,
            args.pasta,
            args.nome,
        )

    # 7. Download URL direta
    if args.download:
        if not args.pasta:
            raise ValueError(
                "--download exige --pasta."
            )

        baixar_url(
            args.download,
            args.pasta,
            args.nome,
        )

    # 8. Custom Node
    if args.node:
        instalar_node(args.node)

    # 9. Servidor
    if not args.no_server:
        subir_servidor_e_tunel()
    else:
        print("\n>> --no-server ativo. Servidor não iniciado.")


if __name__ == "__main__":
    main()
