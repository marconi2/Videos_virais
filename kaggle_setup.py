#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import html
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

# ============================================================
# CONFIGURAÇÃO
# ============================================================

WORKING = Path("/kaggle/working")
COMFY = WORKING / "ComfyUI"

# NÃO apagar nem recriar esta pasta.
PERSIST_ROOT = WORKING / "ComfyUI_Persistent"
PERSIST_MODELS = PERSIST_ROOT / "models"
PERSIST_NODES = PERSIST_ROOT / "custom_nodes"
PERSIST_INPUT = PERSIST_ROOT / "input"
PERSIST_OUTPUT = PERSIST_ROOT / "output"

MODELS = COMFY / "models"
CUSTOM_NODES = COMFY / "custom_nodes"
INPUT_DIR = COMFY / "input"
OUTPUT_DIR = COMFY / "output"

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
    print(">>", " ".join(map(str, cmd)))
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=capture,
    )


def safe_mkdir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def arquivo_valido(path):
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def caminho_dentro_comfy(relativo):
    relativo = (relativo or "").strip().lstrip("/\\")
    destino = (COMFY / relativo).resolve()
    raiz = COMFY.resolve()

    if destino != raiz and raiz not in destino.parents:
        raise ValueError(f"Pasta inválida: {relativo}")

    return destino


# ============================================================
# COMFYUI / DEPENDÊNCIAS
# ============================================================

def garantir_comfy_aimdo():
    """
    Tenta importar primeiro.
    Só instala comfy-aimdo se realmente estiver faltando.
    """

    try:
        import comfy_aimdo  # noqa: F401
        print(">> comfy-aimdo já instalado")
        return
    except ImportError:
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
            "comfy-aimdo foi instalado, mas ainda não pode ser importado."
        ) from e


def instalar_dependencias_comfyui():
    requirements = COMFY / "requirements.txt"

    if not requirements.exists():
        raise FileNotFoundError(
            f"requirements.txt não encontrado: {requirements}"
        )

    print(">> Verificando/reinstalando dependências do ComfyUI...")

    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        requirements,
    ])

    garantir_comfy_aimdo()


def instalar_comfyui():
    if not COMFY.exists():
        print(">> ComfyUI não existe. Clonando...")
        run(["git", "clone", COMFY_REPO, COMFY])
    else:
        print(">> ComfyUI já existe")

    instalar_dependencias_comfyui()


# ============================================================
# PERSISTÊNCIA
# ============================================================

def migrar_conteudo(origem, destino):
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
    origem = Path(origem)
    destino = Path(destino)

    safe_mkdir(destino)

    if origem.is_symlink():
        try:
            if origem.resolve() == destino.resolve():
                return
        except OSError:
            pass
        origem.unlink()

    elif origem.exists():
        if origem.is_dir():
            migrar_conteudo(origem, destino)
            shutil.rmtree(origem)
        else:
            origem.unlink()

    origem.parent.mkdir(parents=True, exist_ok=True)
    origem.symlink_to(destino, target_is_directory=True)


def preparar_armazenamento_persistente():
    """
    Preserva integralmente os dados existentes em ComfyUI_Persistent.
    """

    for pasta in [
        PERSIST_ROOT,
        PERSIST_MODELS,
        PERSIST_NODES,
        PERSIST_INPUT,
        PERSIST_OUTPUT,
    ]:
        safe_mkdir(pasta)

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
# MANAGER
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

def nome_da_url(url):
    nome = Path(urlparse(url).path).name
    return nome or "download.bin"


def baixar_url(url, pasta, nome=None):
    destino_dir = caminho_dentro_comfy(pasta)
    safe_mkdir(destino_dir)

    nome = nome or nome_da_url(url)
    destino = destino_dir / nome

    if arquivo_valido(destino):
        print(f">> Arquivo já existe: {destino}")
        return destino

    print(">> URL:", url)
    print(">> Destino:", destino)

    temporario = destino.with_suffix(destino.suffix + ".part")

    try:
        urllib.request.urlretrieve(url, temporario)
        temporario.replace(destino)
    except Exception:
        try:
            temporario.unlink()
        except OSError:
            pass
        raise

    print(">> Download concluído:", destino)
    return destino


# ============================================================
# CIVITAI
# ============================================================

def extrair_model_id_civitai(link):
    match = re.search(r"civitai\.com/models/(\d+)", link)

    if not match:
        raise ValueError(
            "Não foi possível encontrar o ID do modelo Civitai."
        )

    return match.group(1)


def nome_content_disposition(response):
    cd = response.headers.get("Content-Disposition", "")

    match = re.search(
        r"filename\*=UTF-8''([^;]+)",
        cd,
        flags=re.IGNORECASE,
    )

    if match:
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
    token = os.environ.get("CIVITAI_TOKEN", "").strip()

    if not token:
        raise RuntimeError("CIVITAI_TOKEN não configurado.")

    model_id = extrair_model_id_civitai(link)

    url = (
        f"https://civitai.com/api/download/models/"
        f"{model_id}?token={token}"
    )

    destino_dir = caminho_dentro_comfy(pasta)
    safe_mkdir(destino_dir)

    if nome:
        destino = destino_dir / nome
        if arquivo_valido(destino):
            print(f">> Arquivo já existe: {destino}")
            return destino

    print(f">> Baixando Civitai modelo {model_id}...")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(request) as response:
        nome_header = nome_content_disposition(response)
        nome_final = (
            nome or nome_header or f"civitai_model_{model_id}.bin"
        )

        destino = destino_dir / nome_final

        if arquivo_valido(destino):
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
    nome = url.rstrip("/").split("/")[-1]

    if nome.endswith(".git"):
        nome = nome[:-4]

    if not nome:
        raise ValueError("Nome do repositório inválido.")

    return nome


def instalar_node(url):
    safe_mkdir(CUSTOM_NODES)

    nome = nome_repo_git(url)
    destino = CUSTOM_NODES / nome

    if destino.exists():
        print(f">> Custom Node já existe: {destino}")
        return destino

    print(">> Instalando Custom Node:", url)

    run(["git", "clone", url, destino])

    requirements = destino / "requirements.txt"

    if requirements.exists():
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
    flux_url = os.environ.get("DEFAULT_FLUX_URL", "").strip()
    epic_link = os.environ.get(
        "DEFAULT_EPICREALISM_CIVITAI",
        ""
    ).strip()

    if flux_url:
        try:
            baixar_url(
                flux_url,
                "models/diffusion_models",
            )
        except Exception as e:
            print("!! Erro no Flux padrão:", e)
    else:
        print(">> Flux: nenhuma URL padrão configurada")

    if epic_link:
        try:
            baixar_civitai(
                epic_link,
                "models/checkpoints",
            )
        except Exception as e:
            print("!! Erro no epiCRealism padrão:", e)
    else:
        print(">> epiCRealism: nenhuma URL padrão configurada")


# ============================================================
# CLOUDFLARED
# ============================================================

def cloudflared_esta_executando():
    """
    Verifica se existe processo cloudflared.
    Retorna lista de PIDs.
    """

    resultado = subprocess.run(
        ["pgrep", "-x", "cloudflared"],
        capture_output=True,
        text=True,
        check=False,
    )

    if resultado.returncode != 0:
        return []

    pids = []

    for linha in resultado.stdout.splitlines():
        linha = linha.strip()

        if linha.isdigit():
            pids.append(int(linha))

    return pids


def parar_cloudflared():
    """
    Se houver Cloudflare executando, encerra para criar
    um túnel novo e obter uma nova URL.
    """

    pids = cloudflared_esta_executando()

    if not pids:
        print(">> Nenhum cloudflared em execução.")
        return

    print(">> Cloudflared em execução:", pids)
    print(">> Encerrando para criar um novo túnel...")

    for pid in pids:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass

    # Aguarda encerramento.
    for _ in range(20):
        if not cloudflared_esta_executando():
            break
        time.sleep(0.5)

    # Se ainda houver processo, força.
    restantes = cloudflared_esta_executando()

    for pid in restantes:
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, PermissionError):
            pass


def reparar_cloudflared():
    """
    Corrige o executável existente.
    Se estiver ausente ou inutilizável, baixa novamente.

    A ComfyUI_Persistent NÃO é tocada.
    """

    url = (
        "https://github.com/cloudflare/cloudflared/releases/latest/"
        "download/cloudflared-linux-amd64"
    )

    if CLOUDFLARED.exists():
        print(">> cloudflared já existe")
        print(">> Aplicando chmod +x sempre...")

        try:
            os.chmod(CLOUDFLARED, 0o755)
        except Exception as e:
            print("!! chmod falhou:", e)

        if os.access(CLOUDFLARED, os.X_OK):
            try:
                resultado = subprocess.run(
                    [str(CLOUDFLARED), "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                if resultado.returncode == 0:
                    print(">> cloudflared executável e funcionando.")
                    print(">>", resultado.stdout.strip())
                    return CLOUDFLARED

            except Exception:
                pass

        print("!! cloudflared existente não está utilizável.")
        print(">> Baixando uma cópia nova...")

    temporario = WORKING / "cloudflared.download"

    try:
        if temporario.exists():
            temporario.unlink()

        urllib.request.urlretrieve(url, temporario)
        os.chmod(temporario, 0o755)

        if CLOUDFLARED.exists():
            CLOUDFLARED.unlink()

        temporario.rename(CLOUDFLARED)
        os.chmod(CLOUDFLARED, 0o755)

    except Exception:
        try:
            temporario.unlink()
        except OSError:
            pass
        raise

    if not os.access(CLOUDFLARED, os.X_OK):
        raise PermissionError(
            f"cloudflared não está executável: {CLOUDFLARED}"
        )

    print(">> cloudflared corrigido:", CLOUDFLARED)

    return CLOUDFLARED


def testar_cloudflared(cf):
    resultado = subprocess.run(
        [str(cf), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    if resultado.returncode != 0:
        print(resultado.stdout)
        print(resultado.stderr)
        raise RuntimeError(
            "cloudflared não conseguiu executar."
        )

    print(">>", resultado.stdout.strip())


# ============================================================
# COMFYUI
# ============================================================

def comfyui_esta_executando():
    resultado = subprocess.run(
        ["pgrep", "-f", r"/ComfyUI/main\.py"],
        capture_output=True,
        text=True,
        check=False,
    )

    if resultado.returncode != 0:
        return []

    pids = []

    for linha in resultado.stdout.splitlines():
        linha = linha.strip()
        if linha.isdigit():
            pids.append(int(linha))

    return pids


def parar_comfyui():
    pids = comfyui_esta_executando()

    if not pids:
        print(">> Nenhum ComfyUI antigo em execução.")
        return

    print(">> ComfyUI em execução:", pids)
    print(">> Encerrando para iniciar uma sessão limpa...")

    for pid in pids:
        try:
            os.kill(pid, 15)
        except (ProcessLookupError, PermissionError):
            pass

    for _ in range(20):
        if not comfyui_esta_executando():
            break
        time.sleep(0.5)

    restantes = comfyui_esta_executando()

    for pid in restantes:
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, PermissionError):
            pass


def esperar_porta(host, port, processo, timeout=90):
    inicio = time.time()

    while time.time() - inicio < timeout:

        if processo.poll() is not None:
            return False

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )
        sock.settimeout(0.5)

        try:
            sock.connect((host, port))
            return True
        except OSError:
            time.sleep(1)
        finally:
            sock.close()

    return False


# ============================================================
# BOTÃO HTML
# ============================================================

def mostrar_botao_url(url):
    try:
        from IPython.display import display, HTML

        url_html = html.escape(url, quote=True)

        display(
            HTML(
                f"""
                <div style="
                    margin: 20px 0;
                    padding: 22px;
                    border: 2px solid #22c55e;
                    border-radius: 14px;
                    background: #f0fdf4;
                    text-align: center;
                    max-width: 750px;
                ">

                    <div style="
                        font-size: 24px;
                        font-weight: 700;
                        margin-bottom: 16px;
                    ">
                        🚀 ComfyUI Online
                    </div>

                    <a
                        href="{url_html}"
                        target="_blank"
                        rel="noopener noreferrer"
                        style="
                            display: inline-block;
                            padding: 15px 32px;
                            background: #16a34a;
                            color: #ffffff !important;
                            text-decoration: none;
                            border-radius: 9px;
                            font-size: 18px;
                            font-weight: 700;
                            cursor: pointer;
                        "
                    >
                        🔗 ABRIR COMFYUI
                    </a>

                    <div style="
                        margin-top: 16px;
                        padding: 10px;
                        font-size: 14px;
                        word-break: break-all;
                        background: #ffffff;
                        border-radius: 7px;
                    ">
                        {url_html}
                    </div>

                </div>
                """
            )
        )

    except Exception as e:
        print("!! Falha ao renderizar botão:", e)
        print("URL:", url)


# ============================================================
# SERVIDOR + TÚNEL
# ============================================================

def subir_servidor_e_tunel(cf):
    # Sempre reinicia processos existentes.
    parar_cloudflared()
    parar_comfyui()

    # Sempre garante a permissão.
    os.chmod(cf, 0o755)

    if not os.access(cf, os.X_OK):
        raise PermissionError(
            f"cloudflared sem permissão de execução: {cf}"
        )

    print(">> Subindo ComfyUI...")

    log_file = WORKING / "comfyui.log"

    log = open(
        log_file,
        "w",
        encoding="utf-8",
    )

    comfy = subprocess.Popen(
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

    print(">> PID ComfyUI:", comfy.pid)

    if not esperar_porta(
        COMFY_HOST,
        COMFY_PORT,
        comfy,
        timeout=90,
    ):
        log.flush()

        try:
            texto = log_file.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            texto = ""

        print("\n==========================================")
        print("❌ COMFYUI NÃO INICIOU")
        print("==========================================")
        print(texto[-8000:])

        raise RuntimeError(
            f"ComfyUI não iniciou. Log: {log_file}"
        )

    print(
        f">> ComfyUI online em "
        f"http://{COMFY_HOST}:{COMFY_PORT}"
    )

    print(">> Criando novo Cloudflare Tunnel...")

    tun = subprocess.Popen(
        [
            str(cf),
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

    print(">> PID Cloudflare:", tun.pid)

    url = None
    inicio = time.time()

    while time.time() - inicio < 60:

        linha = tun.stdout.readline()

        if not linha:
            if tun.poll() is not None:
                break

            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            print("[cloudflared]", linha)

        encontrado = re.search(
            r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com",
            linha,
        )

        if encontrado:
            url = encontrado.group(0)
            break

    if not url:
        print("\n==========================================")
        print("❌ URL DO CLOUDFLARE NÃO ENCONTRADA")
        print("==========================================")

        if tun.poll() is not None:
            print(
                "Cloudflared encerrou com código:",
                tun.returncode,
            )

        return

    print("\n==========================================")
    print("🚀 COMFYUI ONLINE")
    print("==========================================")
    print(url)
    print("==========================================")

    # Botão HTML clicável no Kaggle.
    mostrar_botao_url(url)


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
        help="Corrige dependências, comfy-aimdo e cloudflared.",
    )

    parser.add_argument(
        "--civitai",
        help="Link de página de modelo Civitai.",
    )

    parser.add_argument(
        "--download",
        help="URL direta de arquivo/modelo.",
    )

    parser.add_argument(
        "--pasta",
        help="Pasta destino relativa ao ComfyUI.",
    )

    parser.add_argument(
        "--nome",
        help="Nome opcional do arquivo.",
    )

    parser.add_argument(
        "--node",
        help="URL GitHub de Custom Node.",
    )

    parser.add_argument(
        "--no-server",
        action="store_true",
        help="Não iniciar ComfyUI nem Cloudflare.",
    )

    parser.add_argument(
        "--skip-default-models",
        action="store_true",
        help="Não baixar modelos padrão.",
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

    # 4. Modo repair
    if args.repair:
        print("\n>> Modo --repair")
        parar_cloudflared()
        cf = reparar_cloudflared()
        testar_cloudflared(cf)

        print("\n==========================================")
        print("✅ REPARO CONCLUÍDO")
        print("==========================================")
        print("ComfyUI_Persistent foi preservada.")
        return

    # 5. Modelos padrão
    if not args.skip_default_models:
        instalar_modelos_padrao()

    # 6. Civitai
    if args.civitai:
        if not args.pasta:
            raise ValueError("--civitai exige --pasta.")

        baixar_civitai(
            args.civitai,
            args.pasta,
            args.nome,
        )

    # 7. URL direta
    if args.download:
        if not args.pasta:
            raise ValueError("--download exige --pasta.")

        baixar_url(
            args.download,
            args.pasta,
            args.nome,
        )

    # 8. Custom Node
    if args.node:
        instalar_node(args.node)

    # 9. Sem servidor
    if args.no_server:
        print(
            "\n>> --no-server ativo. "
            "Servidor não iniciado."
        )
        return

    # 10. Corrigir/verificar Cloudflare
    cf = reparar_cloudflared()
    testar_cloudflared(cf)

    # 11. Reiniciar ComfyUI + Cloudflare
    subir_servidor_e_tunel(cf)


if __name__ == "__main__":
    main()
