# -*- coding: utf-8 -*-
"""
nodes.py — Custom nodes do ComfyUI para o projeto Videos_virais.

FILOSOFIA (V2): o ComfyUI roda numa maquina fraca (Intel, sem GPU forte) e serve
APENAS como interface de organizacao. Ele NAO gera video localmente. Ele monta o
"pacote" (imagens de referencia + roteiro + prompts + duracoes) e dispara a geracao
pesada no Modal (A100), que acorda sob demanda, gera com o Wan 2.1 e devolve o mp4.
A GPU do Modal desliga sozinha depois (scaledown_window no app.py).

COMO O NO CHAMA O MODAL (decisao tecnica):
A .venv do ComfyUI Desktop NAO tem o pacote 'modal'. O Python global da maquina
(C:\\Python313\\python.exe) TEM o 'modal' instalado e autenticado (~/.modal.toml).
Por isso o no NAO importa 'modal' aqui dentro — ele dispara um SUBPROCESSO chamando
o Python global para rodar 'modal run scripts/generate_video.py' no diretorio do
projeto. Assim nao mexemos na venv do ComfyUI e reaproveitamos 100% do codigo Modal
ja existente.

Nos expostos:
  - VideosViraisConfig : aponta o caminho do projeto e o Python que tem o Modal.
  - VideosViraisGerarNoModal : dispara a geracao no Modal e retorna o caminho do mp4.
"""

import os
import subprocess
import sys
import shutil
import json
from pathlib import Path


# --------------------------------------------------------------------------- #
# Descoberta de caminhos padrao (podem ser sobrescritos no no de Config)
# --------------------------------------------------------------------------- #
def _projeto_padrao() -> str:
    """Tenta achar a pasta do projeto Videos_virais.

    Ordem: variavel de ambiente -> caminho conhecido no Desktop -> vazio.
    """
    env = os.environ.get("VIDEOS_VIRAIS_DIR")
    if env and Path(env).exists():
        return env
    candidato = Path.home() / "Desktop" / "Videos_virais"
    if candidato.exists():
        return str(candidato)
    return ""


def _python_com_modal_padrao() -> str:
    """Python que tem o pacote 'modal' autenticado.

    Preferencia: variavel de ambiente -> C:\\Python313\\python.exe (global desta
    maquina) -> 'python' no PATH como ultimo recurso.
    """
    env = os.environ.get("VIDEOS_VIRAIS_PYTHON")
    if env and Path(env).exists():
        return env
    conhecido = Path(r"C:\Python313\python.exe")
    if conhecido.exists():
        return str(conhecido)
    achado = shutil.which("python")
    return achado or "python"


# --------------------------------------------------------------------------- #
# No 1 — Configuracao (caminhos). Saida vira entrada do no de geracao.
# --------------------------------------------------------------------------- #
class VideosViraisConfig:
    """Define onde esta o projeto e qual Python (com Modal) usar."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "projeto_dir": ("STRING", {"default": _projeto_padrao(), "multiline": False}),
                "python_com_modal": ("STRING", {"default": _python_com_modal_padrao(), "multiline": False}),
            }
        }

    RETURN_TYPES = ("VV_CONFIG",)
    RETURN_NAMES = ("config",)
    FUNCTION = "montar"
    CATEGORY = "Videos Virais"

    def montar(self, projeto_dir, python_com_modal):
        projeto = Path(projeto_dir)
        if not projeto.exists():
            raise RuntimeError(
                f"[Videos Virais] projeto_dir nao existe: {projeto_dir}. "
                f"Aponte para a pasta do projeto (que contem modal_app/ e scripts/)."
            )
        script = projeto / "scripts" / "generate_video.py"
        if not script.exists():
            raise RuntimeError(
                f"[Videos Virais] nao achei scripts/generate_video.py em {projeto_dir}."
            )
        if not Path(python_com_modal).exists():
            raise RuntimeError(
                f"[Videos Virais] python_com_modal nao existe: {python_com_modal}. "
                f"Aponte para o Python que tem o pacote 'modal' instalado e autenticado."
            )
        config = {"projeto_dir": str(projeto), "python": str(python_com_modal)}
        return (config,)


# --------------------------------------------------------------------------- #
# No 2 — Disparar geracao no Modal (subprocesso) e devolver caminho do mp4.
# --------------------------------------------------------------------------- #
class VideosViraisGerarNoModal:
    """Dispara 'modal run scripts/generate_video.py' via Python global.

    Le roteiro.json + timeline.json (ja existentes no projeto), envia as cenas
    para o Modal (Wan 2.1 na A100), monta o mp4 e o baixa para saida/. Retorna o
    caminho do arquivo final como STRING (para um no de texto/preview mostrar).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "config": ("VV_CONFIG",),
                "steps": ("INT", {"default": 40, "min": 1, "max": 100}),
                "fps": ("INT", {"default": 16, "min": 8, "max": 30}),
                "guidance": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 15.0, "step": 0.5}),
                "montar_final": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("caminho_mp4", "log")
    FUNCTION = "gerar"
    CATEGORY = "Videos Virais"
    OUTPUT_NODE = True

    def gerar(self, config, steps, fps, guidance, montar_final):
        projeto = Path(config["projeto_dir"])
        python = config["python"]
        script_rel = os.path.join("scripts", "generate_video.py")

        # Monta o comando: <python global> -m modal run scripts/generate_video.py [args]
        # Usamos '-m modal' para nao depender do 'modal.exe' estar no PATH.
        # OBS: o Modal expoe booleanos como par de flags: --montar-final / --no-montar-final
        # (verificado via 'modal run ... --help'). NAO se passa 'True/False' como valor.
        cmd = [
            python, "-m", "modal", "run", script_rel,
            "--steps", str(int(steps)),
            "--fps", str(int(fps)),
            "--guidance", str(float(guidance)),
            ("--montar-final" if montar_final else "--no-montar-final"),
        ]

        print(f"[Videos Virais] disparando Modal em: {projeto}")
        print(f"[Videos Virais] comando: {' '.join(cmd)}")

        # Roda no diretorio do projeto para os caminhos relativos baterem.
        proc = subprocess.run(
            cmd,
            cwd=str(projeto),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        print(log)

        if proc.returncode != 0:
            raise RuntimeError(
                f"[Videos Virais] o Modal retornou erro (codigo {proc.returncode}). "
                f"Veja o log:\n{log[-2000:]}"
            )

        # Descobre o mp4 final: le o titulo do roteiro para montar o nome.
        caminho_mp4 = self._descobrir_mp4(projeto)
        return (caminho_mp4, log)

    @staticmethod
    def _descobrir_mp4(projeto: Path) -> str:
        """Deduz o caminho do mp4 final a partir do titulo do roteiro.json."""
        titulo = "video"
        roteiro = projeto / "entrada" / "roteiro.json"
        try:
            if roteiro.exists():
                data = json.loads(roteiro.read_text(encoding="utf-8"))
                titulo = data.get("titulo", "video")
        except Exception:
            pass
        final = projeto / "saida" / f"{titulo}_final.mp4"
        if final.exists():
            return str(final)
        # fallback: mp4 mais recente em saida/
        saida = projeto / "saida"
        if saida.exists():
            mp4s = sorted(saida.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if mp4s:
                return str(mp4s[0])
        return "(mp4 nao encontrado — veja o log)"


# --------------------------------------------------------------------------- #
# Registro dos nos (API classica do ComfyUI — compativel com todas as versoes)
# --------------------------------------------------------------------------- #
NODE_CLASS_MAPPINGS = {
    "VideosViraisConfig": VideosViraisConfig,
    "VideosViraisGerarNoModal": VideosViraisGerarNoModal,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideosViraisConfig": "Videos Virais — Config (projeto + Python)",
    "VideosViraisGerarNoModal": "Videos Virais — Gerar no Modal (A100)",
}
