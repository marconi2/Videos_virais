#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
COMFYUI KAGGLE SETUP — VERSÃO FINAL
====================================

Objetivos:
- Preparar/instalar ComfyUI no Kaggle.
- Reconhecer e preservar symlinks existentes.
- Usar /kaggle/working/ComfyUI_Persistent para:
    models/
    custom_nodes/
    input/
    output/
- Preservar modelos e Custom Nodes existentes.
- Nunca apagar conteúdo do armazenamento persistente.
- Corrigir com segurança arquivos ocupando o lugar de diretórios.
- Validar os symlinks antes de continuar.
- Instalar/verificar ComfyUI-Manager.
- Disponibilizar funções para downloads e Custom Nodes.
- Iniciar ComfyUI.
- Iniciar Cloudflared em background sem readline() bloqueante.
- Confirmar que o Cloudflared continua vivo antes de mostrar a URL.
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
CLOUDFLARED_LOG = Path("/kaggle/working/cloudflared.log")

PERSIST_DIRS = (
    "models",
    "custom_nodes",
    "input",
    "output",
)

MANAGER_REPO = (
    "https://github.com/ltdrdata/ComfyUI-Manager.git"
)


# ============================================================
# UTILIDADES
# ============================================================

def log(msg: str = "") -> None:
    print(msg, flush=True)


def run(
    cmd,
    *,
    cwd: Optional[Path] = None,
    check: bool = True,
    capture: bool = False,
):
    log(f">> {' '.join(map(str, cmd))}")

    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=capture,
    )


def download_file(
    url: str,
    destino: Path,
    headers: Optional[dict] = None,
) -> None:

    destino.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    req = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": "Mozilla/5.0"
        },
    )

    with urllib.request.urlopen(req) as response:
        with open(destino, "wb") as f:
            shutil.copyfileobj(response, f)


def arquivo_tem_tamanho(
    path: Path,
    minimo: int = 1024,
) -> bool:

    try:
        return (
            path.is_file()
            and path.stat().st_size >= minimo
        )
    except OSError:
        return False


def safe_backup_path(path: Path) -> Path:

    base = path.with_name(
        path.name + ".backup"
    )

    if (
        not base.exists()
        and not base.is_symlink()
    ):
        return base

    i = 1

    while True:

        candidate = path.with_name(
            f"{path.name}.backup_{i}"
        )

        if (
            not candidate.exists()
            and not candidate.is_symlink()
        ):
            return candidate

        i += 1


# ============================================================
# CAMINHOS DENTRO DO COMFYUI
# ============================================================

def caminho_dentro_comfy(
    relativo: str,
) -> Path:
    """
    Validação lexical.

    Não usa resolve() para validar se o caminho está dentro
    do ComfyUI, pois models/custom_nodes/input/output são
    symlinks para ComfyUI_Persistent.
    """

    relativo = (
        (relativo or "")
        .strip()
        .lstrip("/\\")
    )

    if not relativo:
        return COMFY.absolute()

    parts = Path(relativo).parts

    if any(part == ".." for part in parts):
        raise ValueError(
            f"Pasta inválida: {relativo}"
        )

    candidato = COMFY / relativo

    raiz_abs = COMFY.absolute()
    candidato_abs = candidato.absolute()

    try:
        candidato_abs.relative_to(
            raiz_abs
        )
    except ValueError:
        raise ValueError(
            f"Pasta inválida: {relativo}"
        )

    return candidato_abs


# ============================================================
# PERSISTÊNCIA
# ============================================================

def same_target(
    a: Path,
    b: Path,
) -> bool:
    """
    Compara destinos reais somente para validar symlinks.
    """

    try:

        return (
            a.resolve(strict=True)
            == b.resolve(strict=True)
        )

    except (
        FileNotFoundError,
        OSError,
    ):
        return False


def migrar_conteudo(
    origem: Path,
    destino: Path,
) -> None:
    """
    Migra conteúdo de uma pasta REAL.

    Nunca é chamado sobre symlink válido.

    Nunca sobrescreve algo que já existe
    no armazenamento persistente.
    """

    if (
        not origem.exists()
        or origem.is_symlink()
        or not origem.is_dir()
    ):
        return

    destino.mkdir(
        parents=True,
        exist_ok=True,
    )

    for item in list(origem.iterdir()):

        destino_item = destino / item.name

        if (
            destino_item.exists()
            or destino_item.is_symlink()
        ):
            log(
                f"   ⏭️ Já existe no persistente: "
                f"{item.name}"
            )
            continue

        try:

            shutil.move(
                str(item),
                str(destino_item),
            )

            log(
                f"   📦 Migrado: {item.name}"
            )

        except Exception as e:

            log(
                f"   ⚠️ Não foi possível migrar "
                f"{item.name}: {e}"
            )


def preparar_diretorio_persistente(
    nome: str,
) -> None:
    """
    Prepara:

        models
        custom_nodes
        input
        output

    Casos:

    1. Symlink correto:
       preserva.

    2. Symlink apontando para outro lugar:
       preserva o link antigo como backup e cria
       o link correto.

    3. Diretório normal:
       migra seu conteúdo e transforma em symlink.

    4. Arquivo:
       faz backup e cria symlink.

    5. Não existe:
       cria symlink.

    O conteúdo do PERSIST nunca é apagado.
    """

    origem = COMFY / nome
    destino = PERSIST / nome

    log("")
    log(f"--- {nome} ---")
    log(f"Origem:  {origem}")
    log(f"Destino: {destino}")

    destino.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 1. SYMLINK
    # --------------------------------------------------------

    if origem.is_symlink():

        try:

            if same_target(
                origem,
                destino,
            ):

                log(
                    "   🔗 Symlink correto já existe. "
                    "Preservado."
                )

                return

            alvo = origem.readlink()

            log(
                "   ⚠️ Symlink aponta para outro "
                f"destino: {alvo}"
            )

            backup = safe_backup_path(
                origem
            )

            origem.rename(backup)

            log(
                f"   📦 Symlink antigo preservado em: "
                f"{backup}"
            )

            origem.symlink_to(
                destino,
                target_is_directory=True,
            )

            log(
                "   🔗 Novo symlink criado."
            )

            return

        except OSError as e:

            log(
                f"   ⚠️ Symlink quebrado/inacessível: "
                f"{e}"
            )

            backup = safe_backup_path(
                origem
            )

            origem.rename(backup)

            log(
                f"   📦 Symlink preservado em: "
                f"{backup}"
            )

            origem.symlink_to(
                destino,
                target_is_directory=True,
            )

            log(
                "   🔗 Novo symlink criado."
            )

            return

    # --------------------------------------------------------
    # 2. DIRETÓRIO NORMAL
    # --------------------------------------------------------

    if (
        origem.exists()
        and origem.is_dir()
    ):

        log(
            "   📁 Diretório normal encontrado."
        )

        migrar_conteudo(
            origem,
            destino,
        )

        try:

            origem.rmdir()

            log(
                "   🧹 Diretório vazio removido."
            )

        except OSError as e:

            raise RuntimeError(
                f"O diretório {origem} ainda "
                f"contém arquivos após a migração. "
                f"Nada foi apagado. Detalhe: {e}"
            ) from e

        origem.symlink_to(
            destino,
            target_is_directory=True,
        )

        log(
            "   🔗 Symlink criado."
        )

        return

    # --------------------------------------------------------
    # 3. ARQUIVO NO LUGAR DA PASTA
    # --------------------------------------------------------

    if origem.exists():

        log(
            "   ⚠️ Existe um ARQUIVO onde "
            "deveria haver uma pasta."
        )

        backup = safe_backup_path(
            origem
        )

        origem.rename(backup)

        log(
            f"   📦 Arquivo preservado em: "
            f"{backup}"
        )

        origem.symlink_to(
            destino,
            target_is_directory=True,
        )

        log(
            "   🔗 Symlink criado."
        )

        return

    # --------------------------------------------------------
    # 4. NÃO EXISTE
    # --------------------------------------------------------

    origem.symlink_to(
        destino,
        target_is_directory=True,
    )

    log(
        "   🔗 Symlink criado."
    )


def preparar_armazenamento_persistente() -> None:

    log("")
    log("=" * 70)
    log(
        "💾 PREPARANDO ARMAZENAMENTO PERSISTENTE"
    )
    log("=" * 70)

    COMFY.mkdir(
        parents=True,
        exist_ok=True,
    )

    PERSIST.mkdir(
        parents=True,
        exist_ok=True,
    )

    for nome in PERSIST_DIRS:

        preparar_diretorio_persistente(
            nome
        )

    log("")
    log(
        "✅ Armazenamento persistente preparado."
    )


def validar_armazenamento() -> bool:

    log("")
    log("=" * 70)
    log("🔍 VALIDANDO ARMAZENAMENTO")
    log("=" * 70)

    ok = True

    for nome in PERSIST_DIRS:

        origem = COMFY / nome
        destino = PERSIST / nome

        if not origem.exists():

            log(
                f"❌ {origem} não existe."
            )

            ok = False
            continue

        if not origem.is_symlink():

            log(
                f"❌ {origem} não é symlink."
            )

            ok = False
            continue

        if (
            not destino.exists()
            or not destino.is_dir()
        ):

            log(
                f"❌ Destino persistente "
                f"inválido: {destino}"
            )

            ok = False
            continue

        if not same_target(
            origem,
            destino,
        ):

            log(
                f"❌ Symlink incorreto: "
                f"{origem}"
            )

            ok = False
            continue

        log(
            f"✅ {nome}: symlink correto."
        )

    return ok


# ============================================================
# COMFYUI
# ============================================================

def instalar_comfyui() -> None:

    if (COMFY / "main.py").exists():

        log(
            ">> ComfyUI já existe."
        )

        return

    log(
        ">> Clonando ComfyUI..."
    )

    run([
        "git",
        "clone",
        "--depth",
        "1",
        "https://github.com/comfyanonymous/ComfyUI.git",
        str(COMFY),
    ])


def garantir_comfy_aimdo() -> None:

    try:

        import comfy_aimdo  # noqa: F401

        log(
            ">> comfy-aimdo já instalado"
        )

        return

    except ImportError:
        pass

    log(
        ">> Instalando comfy-aimdo..."
    )

    run([
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "comfy-aimdo",
    ])


def instalar_dependencias_comfyui() -> None:

    requirements = (
        COMFY / "requirements.txt"
    )

    if requirements.exists():

        log("")
        log(
            "📦 Verificando/instalando "
            "dependências do ComfyUI..."
        )

        run([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements),
        ])

    else:

        log(
            "⚠️ requirements.txt não encontrado."
        )

    garantir_comfy_aimdo()


def instalar_manager() -> None:

    manager = (
        COMFY
        / "custom_nodes"
        / "ComfyUI-Manager"
    )

    if manager.exists():

        log(
            ">> ComfyUI-Manager já instalado."
        )

        return

    log(
        ">> Instalando ComfyUI-Manager..."
    )

    run([
        "git",
        "clone",
        "--depth",
        "1",
        MANAGER_REPO,
        str(manager),
    ])


# ============================================================
# DOWNLOADS GENÉRICOS
# ============================================================

def nome_de_url(
    url: str,
) -> str:

    url_sem_query = (
        url
        .split("?", 1)[0]
        .split("#", 1)[0]
    )

    nome = Path(
        url_sem_query
    ).name

    if not nome:

        raise ValueError(
            "Não foi possível descobrir "
            f"o nome do arquivo: {url}"
        )

    return nome


def download_url(
    url: str,
    pasta_relativa: str,
    nome_arquivo: Optional[str] = None,
) -> Path:
    """
    Download genérico.

    Exemplo:

    download_url(
        "https://site/model.safetensors",
        "models/checkpoints"
    )
    """

    destino_dir = caminho_dentro_comfy(
        pasta_relativa
    )

    destino_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    nome = (
        nome_arquivo
        or nome_de_url(url)
    )

    destino = destino_dir / nome

    if arquivo_tem_tamanho(
        destino
    ):

        log(
            "⏭️ Já existe, não baixando "
            f"novamente: {destino}"
        )

        return destino

    log(
        f"⬇️ Baixando: {url}"
    )

    log(
        f"   Destino: {destino}"
    )

    download_file(
        url,
        destino,
    )

    if not arquivo_tem_tamanho(
        destino
    ):

        raise RuntimeError(
            f"Download aparentemente "
            f"inválido: {destino}"
        )

    log(
        f"✅ Download concluído: {destino}"
    )

    return destino


def baixar_civitai(
    url: str,
    pasta_relativa: str,
    nome_arquivo: Optional[str] = None,
) -> Path:
    """
    Download usando CIVITAI_TOKEN.
    """

    token = (
        os.environ
        .get("CIVITAI_TOKEN", "")
        .strip()
    )

    if not token:

        raise RuntimeError(
            "CIVITAI_TOKEN não configurado."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
    }

    destino_dir = caminho_dentro_comfy(
        pasta_relativa
    )

    destino_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    nome = (
        nome_arquivo
        or nome_de_url(url)
    )

    destino = destino_dir / nome

    if arquivo_tem_tamanho(
        destino
    ):

        log(
            f"⏭️ Civitai: arquivo já existe: "
            f"{destino}"
        )

        return destino

    log(
        f"⬇️ Baixando Civitai: {url}"
    )

    download_file(
        url,
        destino,
        headers=headers,
    )

    if not arquivo_tem_tamanho(
        destino
    ):

        raise RuntimeError(
            f"Download Civitai inválido: "
            f"{destino}"
        )

    log(
        f"✅ Civitai concluído: {destino}"
    )

    return destino


# ============================================================
# CUSTOM NODES
# ============================================================

def instalar_custom_node(
    repo_url: str,
    nome: Optional[str] = None,
) -> Path:
    """
    Instala Custom Node dentro de custom_nodes,
    que aponta para o armazenamento persistente.
    """

    nodes_dir = caminho_dentro_comfy(
        "custom_nodes"
    )

    nodes_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    repo_name = (
        nome
        or repo_url.rstrip("/").split("/")[-1]
    )

    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    destino = (
        nodes_dir / repo_name
    )

    if destino.exists():

        log(
            f"⏭️ Custom Node já existe: "
            f"{repo_name}"
        )

        return destino

    log(
        f"🧩 Instalando Custom Node: "
        f"{repo_url}"
    )

    run([
        "git",
        "clone",
        "--depth",
        "1",
        repo_url,
        str(destino),
    ])

    log(
        f"✅ Custom Node instalado: "
        f"{destino}"
    )

    return destino


# ============================================================
# PROCESSOS
# ============================================================

def pids_comfyui() -> list[int]:

    try:

        result = subprocess.run(
            [
                "pgrep",
                "-f",
                r"/ComfyUI/main\.py",
            ],
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

    log(
        f"🛑 Parando ComfyUI: {pids}"
    )

    for pid in pids:

        try:
            os.kill(
                pid,
                signal.SIGTERM,
            )

        except ProcessLookupError:
            pass

    for _ in range(20):

        if not pids_comfyui():
            return

        time.sleep(0.5)

    for pid in pids_comfyui():

        try:
            os.kill(
                pid,
                signal.SIGKILL,
            )

        except ProcessLookupError:
            pass


def pids_cloudflared() -> list[int]:

    try:

        result = subprocess.run(
            [
                "pgrep",
                "-x",
                "cloudflared",
            ],
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

    log(
        f"🛑 Parando Cloudflare anterior: "
        f"{pids}"
    )

    for pid in pids:

        try:
            os.kill(
                pid,
                signal.SIGTERM,
            )

        except ProcessLookupError:
            pass

    for _ in range(20):

        if not pids_cloudflared():
            return

        time.sleep(0.5)

    for pid in pids_cloudflared():

        try:
            os.kill(
                pid,
                signal.SIGKILL,
            )

        except ProcessLookupError:
            pass


# ============================================================
# CLOUDFLARED
# ============================================================

def garantir_cloudflared() -> Path:

    if CLOUDFLARED.exists():

        try:

            CLOUDFLARED.chmod(
                0o755
            )

            teste = subprocess.run(
                [
                    str(CLOUDFLARED),
                    "--version",
                ],
                capture_output=True,
                text=True,
            )

            if teste.returncode == 0:

                log(
                    ">> cloudflared já está instalado."
                )

                return CLOUDFLARED

        except Exception:
            pass

        backup = safe_backup_path(
            CLOUDFLARED
        )

        log(
            "⚠️ cloudflared inválido. "
            f"Preservando em {backup}"
        )

        CLOUDFLARED.rename(
            backup
        )

    url = (
        "https://github.com/cloudflare/"
        "cloudflared/releases/latest/"
        "download/cloudflared-linux-amd64"
    )

    log(
        ">> Baixando cloudflared..."
    )

    download_file(
        url,
        CLOUDFLARED,
    )

    CLOUDFLARED.chmod(
        0o755
    )

    teste = subprocess.run(
        [
            str(CLOUDFLARED),
            "--version",
        ],
        capture_output=True,
        text=True,
    )

    if teste.returncode != 0:

        raise RuntimeError(
            "cloudflared baixado não "
            "executou corretamente."
        )

    log(
        "✅ cloudflared pronto."
    )

    return CLOUDFLARED


# ============================================================
# REDE
# ============================================================

def porta_aberta(
    host: str,
    port: int,
) -> bool:

    sock = socket.socket()

    sock.settimeout(1)

    try:

        sock.connect(
            (host, port)
        )

        return True

    except OSError:

        return False

    finally:

        sock.close()


# ============================================================
# COMFYUI + CLOUDFLARE
# ============================================================

def subir_servidor_e_tunel(
    cf: Path,
) -> None:

    log("")
    log("=" * 70)
    log("🚀 INICIANDO COMFYUI")
    log("=" * 70)

    # --------------------------------------------------------
    # Encerra processos antigos.
    # Isso garante um novo Quick Tunnel.
    # --------------------------------------------------------

    parar_cloudflared()
    parar_comfyui()

    cf.chmod(0o755)

    # --------------------------------------------------------
    # Inicia ComfyUI
    # --------------------------------------------------------

    log(
        ">> Iniciando ComfyUI..."
    )

    log_file = open(
        COMFY_LOG,
        "w",
        encoding="utf-8",
    )

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

    log(
        f"   PID ComfyUI: "
        f"{processo_comfy.pid}"
    )

    log(
        f"   Log: {COMFY_LOG}"
    )

    # --------------------------------------------------------
    # Aguarda ComfyUI
    # --------------------------------------------------------

    pronto = False

    for _ in range(90):

        if processo_comfy.poll() is not None:

            raise RuntimeError(
                "ComfyUI encerrou durante "
                "a inicialização. "
                f"Consulte {COMFY_LOG}"
            )

        if porta_aberta(
            "127.0.0.1",
            COMFY_PORT,
        ):

            pronto = True
            break

        time.sleep(1)

    if not pronto:

        raise RuntimeError(
            f"ComfyUI não abriu a porta "
            f"{COMFY_PORT} em 90 segundos. "
            f"Consulte {COMFY_LOG}"
        )

    log(
        "✅ ComfyUI está respondendo."
    )

    # --------------------------------------------------------
    # Prepara log do Cloudflare
    # --------------------------------------------------------

    try:

        CLOUDFLARED_LOG.unlink()

    except FileNotFoundError:

        pass

    # --------------------------------------------------------
    # Cloudflared em BACKGROUND
    #
    # Não usamos stdout.readline().
    # Isso evita bloquear o notebook.
    # --------------------------------------------------------

    log(
        ">> Iniciando Cloudflare Tunnel..."
    )

    tunnel_handle = open(
        CLOUDFLARED_LOG,
        "w",
        encoding="utf-8",
    )

    processo_cf = subprocess.Popen(
        [
            str(cf),
            "tunnel",
            "--url",
            f"http://127.0.0.1:{COMFY_PORT}",
            "--no-autoupdate",
        ],
        stdout=tunnel_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    log(
        f"   PID Cloudflared: "
        f"{processo_cf.pid}"
    )

    log(
        f"   Log: {CLOUDFLARED_LOG}"
    )

    # --------------------------------------------------------
    # Aguarda URL
    # --------------------------------------------------------

    url_tunel = None

    inicio = time.time()

    padrao_url = re.compile(
        r"https://[a-zA-Z0-9.-]+"
        r"\.trycloudflare\.com"
    )

    while time.time() - inicio < 30:

        codigo = processo_cf.poll()

        if codigo is not None:

            log(
                "❌ Cloudflared encerrou."
            )

            log(
                f"   Código: {codigo}"
            )

            break

        try:

            texto_log = (
                CLOUDFLARED_LOG.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            )

        except Exception:

            texto_log = ""

        encontrado = padrao_url.search(
            texto_log
        )

        if encontrado:

            url_tunel = (
                encontrado.group(0)
            )

            log("")
            log(
                "🌐 URL DO CLOUDFLARE "
                "ENCONTRADA:"
            )

            log(
                url_tunel
            )

            # A URL só é aceita se o
            # processo ainda estiver vivo.
            if processo_cf.poll() is None:
                break

        time.sleep(1)

    # O processo filho continua independente.
    tunnel_handle.close()

    # --------------------------------------------------------
    # Falha ao obter URL
    # --------------------------------------------------------

    if not url_tunel:

        log("")
        log(
            "❌ Não foi possível obter "
            "a URL do Cloudflare."
        )

        log("")
        log(
            "📄 Últimas linhas do log:"
        )

        try:

            texto = (
                CLOUDFLARED_LOG.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            )

            print(
                texto[-6000:]
            )

        except Exception as e:

            log(
                f"Erro lendo log: {e}"
            )

        return

    # --------------------------------------------------------
    # Confirma que continua vivo
    # --------------------------------------------------------

    time.sleep(2)

    if processo_cf.poll() is not None:

        log("")
        log(
            "❌ Cloudflared morreu "
            "depois de fornecer a URL."
        )

        log(
            "A URL NÃO será apresentada "
            "como válida."
        )

        return

    log("")
    log(
        "✅ CLOUDFLARED CONTINUA RODANDO."
    )

    log(
        f"   PID: {processo_cf.pid}"
    )

    # --------------------------------------------------------
    # Resultado
    # --------------------------------------------------------

    log("")
    log("=" * 70)
    log("🌐 COMFYUI ONLINE")
    log("=" * 70)
    log(
        f"URL: {url_tunel}"
    )
    log("=" * 70)

    # --------------------------------------------------------
    # Botão Kaggle
    # --------------------------------------------------------

    try:

        from IPython.display import (
            HTML,
            display,
        )

        html = f"""
        <div style="margin:15px 0;">
            <a href="{url_tunel}"
               target="_blank"
               style="
               display:inline-block;
               padding:14px 22px;
               background:#222;
               color:white;
               border-radius:8px;
               text-decoration:none;
               font-weight:bold;
               font-size:16px;">
                🚀 ABRIR COMFYUI
            </a>
        </div>
        """

        display(
            HTML(html)
        )

    except Exception:
        pass


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    log("")
    log("=" * 70)
    log("COMFYUI KAGGLE SETUP")
    log("=" * 70)

    # --------------------------------------------------------
    # 1. ComfyUI
    # --------------------------------------------------------

    instalar_comfyui()

    # --------------------------------------------------------
    # 2. Dependências
    # --------------------------------------------------------

    instalar_dependencias_comfyui()

    # --------------------------------------------------------
    # 3. Persistência
    # --------------------------------------------------------

    preparar_armazenamento_persistente()

    # --------------------------------------------------------
    # 4. Validação
    # --------------------------------------------------------

    if not validar_armazenamento():

        raise RuntimeError(
            "A estrutura persistente "
            "não passou na validação."
        )

    # --------------------------------------------------------
    # 5. Manager
    # --------------------------------------------------------

    instalar_manager()

    # --------------------------------------------------------
    # 6. Cloudflared
    # --------------------------------------------------------

    cf = garantir_cloudflared()

    # --------------------------------------------------------
    # 7. Servidor + túnel
    # --------------------------------------------------------

    subir_servidor_e_tunel(
        cf
    )

    log("")
    log("=" * 70)
    log("✅ SETUP FINALIZADO")
    log("=" * 70)
    log(
        "Modelos existentes preservados."
    )
    log(
        "Custom Nodes existentes preservados."
    )
    log(
        "Armazenamento persistente ativo."
    )
    log("=" * 70)


if __name__ == "__main__":
    main()
