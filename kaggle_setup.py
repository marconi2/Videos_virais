#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
COMFYUI KAGGLE SETUP
--------------------
Bootstrap seguro para ComfyUI no Kaggle.

- Reconhece symlinks existentes.
- Preserva modelos e Custom Nodes.
- Prepara ComfyUI_Persistent sem apagar conteúdo.
- Trata arquivos ocupando o lugar de diretórios com backup.
- Não usa resolve() para validar caminhos internos ao ComfyUI.
- Instala dependências, Manager e cloudflared.
- Pode ser importado para usar download_url(), baixar_civitai()
  e instalar_custom_node().
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional


# ============================================================
# CONFIGURAÇÃO
# ============================================================

COMFY = Path("/kaggle/working/ComfyUI")
PERSIST = Path("/kaggle/working/ComfyUI_Persistent")
CLOUDFLARED = Path("/kaggle/working/cloudflared")

COMFY_PORT = 8188
COMFY_LOG = Path("/kaggle/working/comfyui.log")

PERSIST_DIRS = (
    "models",
    "custom_nodes",
    "input",
    "output",
)

MANAGER_REPO = "https://github.com/ltdrdata/ComfyUI-Manager.git"


# ============================================================
# UTILIDADES
# ============================================================

def log(msg: str = "") -> None:
    print(msg, flush=True)


def run(cmd, *, cwd: Optional[Path] = None, check: bool = True,
        capture: bool = False):
    log(f">> {' '.join(map(str, cmd))}")
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=capture,
    )


def download_file(url: str, destino: Path,
                  headers: Optional[dict] = None) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(req) as response, open(destino, "wb") as f:
        shutil.copyfileobj(response, f)


def safe_backup_path(path: Path) -> Path:
    base = path.with_name(path.name + ".backup")
    if not base.exists() and not base.is_symlink():
        return base

    i = 1
    while True:
        candidate = path.with_name(f"{path.name}.backup_{i}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        i += 1


def arquivo_tem_tamanho(path: Path, minimo: int = 1024) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= minimo
    except OSError:
        return False


# ============================================================
# CAMINHO DENTRO DO COMFYUI
# ============================================================

def caminho_dentro_comfy(relativo: str) -> Path:
    """
    Validação lexical.

    Não usa resolve() para validar o caminho, porque COMFYUI contém
    symlinks para ComfyUI_Persistent.
    """
    relativo = (relativo or "").strip().lstrip("/\\")

    if not relativo:
        return COMFY.absolute()

    parts = Path(relativo).parts

    if any(part == ".." for part in parts):
        raise ValueError(f"Pasta inválida: {relativo}")

    candidato = COMFY / relativo
    raiz_abs = COMFY.absolute()
    candidato_abs = candidato.absolute()

    try:
        candidato_abs.relative_to(raiz_abs)
    except ValueError:
        raise ValueError(f"Pasta inválida: {relativo}")

    return candidato_abs


# ============================================================
# SYMLINK / PERSISTÊNCIA
# ============================================================

def same_target(a: Path, b: Path) -> bool:
    """Compara destinos reais apenas para validar symlinks."""
    try:
        return a.resolve(strict=True) == b.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return False


def migrar_conteudo(origem: Path, destino: Path) -> None:
    """
    Migra conteúdo de uma pasta REAL para o persistente.

    Nunca é chamado sobre um symlink válido.
    Nunca sobrescreve um item já existente no destino.
    """
    if not origem.exists() or origem.is_symlink() or not origem.is_dir():
        return

    destino.mkdir(parents=True, exist_ok=True)

    for item in list(origem.iterdir()):
        destino_item = destino / item.name

        if destino_item.exists() or destino_item.is_symlink():
            log(f"   ⏭️ Já existe no persistente: {item.name}")
            continue

        try:
            shutil.move(str(item), str(destino_item))
            log(f"   📦 Migrado: {item.name}")
        except Exception as e:
            log(f"   ⚠️ Não foi possível migrar {item.name}: {e}")


def preparar_diretorio_persistente(nome: str) -> None:
    """
    Prepara models/custom_nodes/input/output.

    Regras:
    - symlink correto: preserva;
    - diretório normal: migra conteúdo e transforma em symlink;
    - arquivo no lugar da pasta: faz backup e cria symlink;
    - symlink incorreto/quebrado: faz backup do link e cria o correto;
    - nunca apaga o conteúdo do destino persistente.
    """
    origem = COMFY / nome
    destino = PERSIST / nome

    log(f"\n--- {nome} ---")
    log(f"Origem:   {origem}")
    log(f"Destino:  {destino}")

    destino.mkdir(parents=True, exist_ok=True)

    # 1. Symlink existente
    if origem.is_symlink():
        try:
            if same_target(origem, destino):
                log("   🔗 Symlink correto já existe. Preservado.")
                return

            alvo = origem.readlink()
            log(f"   ⚠️ Symlink aponta para outro destino: {alvo}")

            backup = safe_backup_path(origem)
            origem.rename(backup)
            log(f"   📦 Symlink antigo preservado em: {backup}")

            origem.symlink_to(destino, target_is_directory=True)
            log("   🔗 Novo symlink criado.")
            return

        except OSError as e:
            log(f"   ⚠️ Symlink quebrado/inacessível: {e}")

            backup = safe_backup_path(origem)
            origem.rename(backup)
            log(f"   📦 Symlink preservado em: {backup}")

            origem.symlink_to(destino, target_is_directory=True)
            log("   🔗 Novo symlink criado.")
            return

    # 2. Diretório normal
    if origem.exists() and origem.is_dir():
        log("   📁 Diretório normal encontrado.")
        migrar_conteudo(origem, destino)

        try:
            origem.rmdir()
            log("   🧹 Diretório vazio removido.")
        except OSError as e:
            raise RuntimeError(
                f"O diretório {origem} ainda contém arquivos após a "
                f"migração. Nada foi apagado. Detalhe: {e}"
            ) from e

        origem.symlink_to(destino, target_is_directory=True)
        log("   🔗 Symlink criado.")
        return

    # 3. Arquivo no lugar da pasta
    if origem.exists():
        log("   ⚠️ Existe um ARQUIVO onde deveria haver uma pasta.")
        backup = safe_backup_path(origem)
        origem.rename(backup)
        log(f"   📦 Arquivo preservado em: {backup}")

        origem.symlink_to(destino, target_is_directory=True)
        log("   🔗 Symlink criado.")
        return

    # 4. Não existe
    origem.symlink_to(destino, target_is_directory=True)
    log("   🔗 Symlink criado.")


def preparar_armazenamento_persistente() -> None:
    log("\n" + "=" * 70)
    log("💾 PREPARANDO ARMAZENAMENTO PERSISTENTE")
    log("=" * 70)

    COMFY.mkdir(parents=True, exist_ok=True)
    PERSIST.mkdir(parents=True, exist_ok=True)

    for nome in PERSIST_DIRS:
        preparar_diretorio_persistente(nome)

    log("\n✅ Armazenamento persistente preparado.")


def validar_armazenamento() -> bool:
    log("\n" + "=" * 70)
    log("🔍 VALIDANDO ARMAZENAMENTO")
    log("=" * 70)

    ok = True

    for nome in PERSIST_DIRS:
        origem = COMFY / nome
        destino = PERSIST / nome

        if not origem.exists():
            log(f"❌ {origem} não existe.")
            ok = False
            continue

        if not origem.is_symlink():
            log(f"❌ {origem} não é symlink.")
            ok = False
            continue

        if not destino.exists() or not destino.is_dir():
            log(f"❌ Destino persistente inválido: {destino}")
            ok = False
            continue

        if not same_target(origem, destino):
            log(f"❌ Symlink incorreto: {origem}")
            ok = False
            continue

        log(f"✅ {nome}: symlink correto.")

    return ok


# ============================================================
# COMFYUI
# ============================================================

def instalar_comfyui() -> None:
    if (COMFY / "main.py").exists():
        log(">> ComfyUI já existe.")
        return

    log(">> Clonando ComfyUI...")
    run([
        "git", "clone", "--depth", "1",
        "https://github.com/comfyanonymous/ComfyUI.git",
        str(COMFY),
    ])


def garantir_comfy_aimdo() -> None:
    try:
        import comfy_aimdo  # noqa: F401
        log(">> comfy-aimdo já instalado")
        return
    except ImportError:
        pass

    log(">> Instalando comfy-aimdo...")
    run([
        sys.executable, "-m", "pip", "install", "-q", "comfy-aimdo"
    ])


def instalar_dependencias_comfyui() -> None:
    requirements = COMFY / "requirements.txt"

    if requirements.exists():
        log("\n📦 Verificando/instalando dependências do ComfyUI...")
        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements),
        ])
    else:
        log("⚠️ requirements.txt não encontrado.")

    garantir_comfy_aimdo()


def instalar_manager() -> None:
    manager = COMFY / "custom_nodes" / "ComfyUI-Manager"

    if manager.exists():
        log(">> ComfyUI-Manager já instalado.")
        return

    log(">> Instalando ComfyUI-Manager...")
    run([
        "git", "clone", "--depth", "1",
        MANAGER_REPO,
        str(manager),
    ])


# ============================================================
# DOWNLOADS
# ============================================================

def nome_de_url(url: str) -> str:
    url_sem_query = url.split("?", 1)[0].split("#", 1)[0]
    nome = Path(url_sem_query).name

    if not nome:
        raise ValueError(
            f"Não foi possível descobrir o nome do arquivo: {url}"
        )

    return nome


def download_url(
    url: str,
    pasta_relativa: str,
    nome_arquivo: Optional[str] = None,
) -> Path:
    """Download genérico para qualquer pasta dentro do ComfyUI."""
    destino_dir = caminho_dentro_comfy(pasta_relativa)
    destino_dir.mkdir(parents=True, exist_ok=True)

    nome = nome_arquivo or nome_de_url(url)
    destino = destino_dir / nome

    if arquivo_tem_tamanho(destino):
        log(f"⏭️ Já existe, não baixando novamente: {destino}")
        return destino

    log(f"⬇️ Baixando: {url}")
    log(f"   Destino: {destino}")

    download_file(url, destino)

    if not arquivo_tem_tamanho(destino):
        raise RuntimeError(f"Download aparentemente inválido: {destino}")

    log(f"✅ Download concluído: {destino}")
    return destino


def baixar_civitai(
    url: str,
    pasta_relativa: str,
    nome_arquivo: Optional[str] = None,
) -> Path:
    """Download usando CIVITAI_TOKEN."""
    token = os.environ.get("CIVITAI_TOKEN", "").strip()

    if not token:
        raise RuntimeError("CIVITAI_TOKEN não configurado.")

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
    }

    destino_dir = caminho_dentro_comfy(pasta_relativa)
    destino_dir.mkdir(parents=True, exist_ok=True)

    nome = nome_arquivo or nome_de_url(url)
    destino = destino_dir / nome

    if arquivo_tem_tamanho(destino):
        log(f"⏭️ Civitai: arquivo já existe: {destino}")
        return destino

    log(f"⬇️ Baixando Civitai: {url}")
    download_file(url, destino, headers=headers)

    if not arquivo_tem_tamanho(destino):
        raise RuntimeError(f"Download Civitai inválido: {destino}")

    log(f"✅ Civitai concluído: {destino}")
    return destino


# ============================================================
# CUSTOM NODES
# ============================================================

def instalar_custom_node(
    repo_url: str,
    nome: Optional[str] = None,
) -> Path:
    """Instala um Custom Node no diretório persistente via symlink."""
    nodes_dir = caminho_dentro_comfy("custom_nodes")
    nodes_dir.mkdir(parents=True, exist_ok=True)

    repo_name = nome or repo_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    destino = nodes_dir / repo_name

    if destino.exists():
        log(f"⏭️ Custom Node já existe: {repo_name}")
        return destino

    log(f"🧩 Instalando Custom Node: {repo_url}")

    run([
        "git", "clone", "--depth", "1",
        repo_url,
        str(destino),
    ])

    log(f"✅ Custom Node instalado: {destino}")
    return destino


# ============================================================
# PROCESSOS
# ============================================================

def pids_comfyui() -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", r"/ComfyUI/main\.py"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        return [
            int(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]
    except Exception:
        return []


def parar_comfyui() -> None:
    pids = pids_comfyui()

    if not pids:
        return

    log(f"🛑 Parando ComfyUI: {pids}")

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for _ in range(20):
        if not pids_comfyui():
            return
        time.sleep(0.5)

    for pid in pids_comfyui():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def pids_cloudflared() -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "cloudflared"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        return [
            int(line.strip())
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]
    except Exception:
        return []


def parar_cloudflared() -> None:
    pids = pids_cloudflared()

    if not pids:
        return

    log(f"🛑 Parando Cloudflare anterior: {pids}")

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for _ in range(20):
        if not pids_cloudflared():
            return
        time.sleep(0.5)

    for pid in pids_cloudflared():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# ============================================================
# CLOUDFLARED
# ============================================================

def garantir_cloudflared() -> Path:
    if CLOUDFLARED.exists():
        try:
            CLOUDFLARED.chmod(0o755)

            teste = subprocess.run(
                [str(CLOUDFLARED), "--version"],
                capture_output=True,
                text=True,
            )

            if teste.returncode == 0:
                log(">> cloudflared já está instalado.")
                return CLOUDFLARED
        except Exception:
            pass

        backup = safe_backup_path(CLOUDFLARED)
        log(f"⚠️ cloudflared inválido. Preservando em {backup}")
        CLOUDFLARED.rename(backup)

    url = (
        "https://github.com/cloudflare/cloudflared/releases/latest/"
        "download/cloudflared-linux-amd64"
    )

    log(">> Baixando cloudflared...")
    download_file(url, CLOUDFLARED)
    CLOUDFLARED.chmod(0o755)

    teste = subprocess.run(
        [str(CLOUDFLARED), "--version"],
        capture_output=True,
        text=True,
    )

    if teste.returncode != 0:
        raise RuntimeError(
            "cloudflared baixado não executou corretamente."
        )

    log("✅ cloudflared pronto.")
    return CLOUDFLARED


# ============================================================
# SERVIDOR + TÚNEL
# ============================================================

def porta_aberta(host: str, port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(1)

    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def subir_servidor_e_tunel(cf: Path) -> None:
    log("\n" + "=" * 70)
    log("🚀 INICIANDO COMFYUI")
    log("=" * 70)

    parar_cloudflared()
    parar_comfyui()

    cf.chmod(0o755)

    log(">> Iniciando ComfyUI...")

    log_file = open(COMFY_LOG, "w", encoding="utf-8")

    processo_comfy = subprocess.Popen(
        [
            sys.executable,
            str(COMFY / "main.py"),
            "--listen",
            "127.0.0.1",
            "--port",
            str(COMFY_PORT),
        ],
        cwd=str(COMFY),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    log(f"   PID ComfyUI: {processo_comfy.pid}")
    log(f"   Log: {COMFY_LOG}")

    pronto = False

    for _ in range(90):
        if processo_comfy.poll() is not None:
            raise RuntimeError(
                f"ComfyUI encerrou durante a inicialização. "
                f"Consulte {COMFY_LOG}"
            )

        if porta_aberta("127.0.0.1", COMFY_PORT):
            pronto = True
            break

        time.sleep(1)

    if not pronto:
        raise RuntimeError(
            f"ComfyUI não abriu a porta {COMFY_PORT} em 90 segundos. "
            f"Consulte {COMFY_LOG}"
        )

    log("✅ ComfyUI está respondendo.")
    log(">> Iniciando Cloudflare Tunnel...")

    processo_cf = subprocess.Popen(
        [
            str(cf),
            "tunnel",
            "--url",
            f"http://127.0.0.1:{COMFY_PORT}",
            "--no-autoupdate",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    url_tunel = None
    inicio = time.time()
    padrao = re.compile(
        r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com"
    )

    while time.time() - inicio < 60:
        if processo_cf.poll() is not None:
            break

        linha = processo_cf.stdout.readline()

        if linha:
            print(linha.rstrip())

            encontrado = padrao.search(linha)
            if encontrado:
                url_tunel = encontrado.group(0)
                break
        else:
            time.sleep(0.2)

    if not url_tunel:
        log("⚠️ URL automática do Cloudflare não foi encontrada.")
        log("Consulte a saída acima para diagnóstico.")
        return

    log("\n" + "=" * 70)
    log("🌐 COMFYUI ONLINE")
    log("=" * 70)
    log(f"URL: {url_tunel}")

    try:
        from IPython.display import HTML, display

        html = f"""
        <div style="margin:15px 0;">
            <a href="{url_tunel}" target="_blank"
               style="
               display:inline-block;
               padding:12px 20px;
               background:#222;
               color:white;
               border-radius:8px;
               text-decoration:none;
               font-weight:bold;">
                🚀 ABRIR COMFYUI
            </a>
        </div>
        """

        display(HTML(html))
    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    log("\n" + "=" * 70)
    log("COMFYUI KAGGLE SETUP")
    log("=" * 70)

    instalar_comfyui()
    instalar_dependencias_comfyui()

    preparar_armazenamento_persistente()

    if not validar_armazenamento():
        raise RuntimeError(
            "A estrutura persistente não passou na validação."
        )

    instalar_manager()

    cf = garantir_cloudflared()
    subir_servidor_e_tunel(cf)

    log("\n" + "=" * 70)
    log("✅ SETUP FINALIZADO")
    log("=" * 70)
    log("Modelos existentes preservados.")
    log("Custom Nodes existentes preservados.")
    log("Armazenamento persistente ativo.")
    log("=" * 70)


if __name__ == "__main__":
    main()
