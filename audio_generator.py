#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_generator.py — Gera as narracoes (voz em off) LOCALMENTE, sem GPU.

Roda na sua maquina. Le entrada/roteiro.json, gera um MP3 por cena usando
edge-tts (vozes neurais da Microsoft, gratuitas) e mede a duracao de cada
audio. A duracao e o que define quanto tempo de video cada cena precisa.

Saida:
  entrada/audio/cena_01.mp3, cena_02.mp3, ...
  entrada/timeline.json   (id da cena, arquivo de audio, duracao em segundos)

Uso:
  pip install edge-tts mutagen
  python audio_generator.py

Opcional:
  python audio_generator.py --voz pt-BR-AntonioNeural
  python audio_generator.py --roteiro entrada/roteiro.json

Vozes PT-BR comuns: pt-BR-FranciscaNeural (fem), pt-BR-AntonioNeural (masc).
Liste todas com:  edge-tts --list-voices
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENTRADA = BASE / "entrada"
AUDIO_DIR = ENTRADA / "audio"


def parse_args():
    p = argparse.ArgumentParser(description="Gera narracoes (edge-tts) por cena.")
    p.add_argument("--roteiro", default=str(ENTRADA / "roteiro.json"),
                   help="Caminho do roteiro.json")
    p.add_argument("--voz", default="pt-BR-FranciscaNeural",
                   help="Voz edge-tts (padrao: pt-BR-FranciscaNeural)")
    p.add_argument("--rate", default="+0%",
                   help="Velocidade da fala, ex: -10%%, +0%%, +10%%")
    return p.parse_args()


def carregar_roteiro(caminho: str) -> dict:
    path = Path(caminho)
    if not path.exists():
        print(f"[ERRO] Roteiro nao encontrado: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def gerar_mp3(texto: str, voz: str, rate: str, destino: Path):
    """Gera um MP3 a partir do texto usando edge-tts."""
    import edge_tts
    comm = edge_tts.Communicate(texto, voz, rate=rate)
    await comm.save(str(destino))


def medir_duracao(mp3_path: Path) -> float:
    """Mede a duracao do MP3 em segundos (usa mutagen)."""
    try:
        from mutagen.mp3 import MP3
        return round(float(MP3(str(mp3_path)).info.length), 2)
    except Exception as e:
        print(f"[AVISO] Nao foi possivel medir duracao de {mp3_path.name}: {e}")
        return 0.0


def main():
    args = parse_args()
    roteiro = carregar_roteiro(args.roteiro)
    cenas = roteiro.get("cenas", [])
    if not cenas:
        print("[ERRO] roteiro.json nao tem 'cenas'.")
        sys.exit(1)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    timeline = {"titulo": roteiro.get("titulo", "video"), "cenas": []}

    print(f"Gerando narracoes com a voz '{args.voz}' (rate {args.rate})...\n")
    for cena in cenas:
        cid = cena.get("id")
        texto = (cena.get("narracao") or "").strip()
        if not texto:
            print(f"[cena {cid}] sem narracao — pulando.")
            continue

        nome = f"cena_{int(cid):02d}.mp3"
        destino = AUDIO_DIR / nome
        try:
            asyncio.run(gerar_mp3(texto, args.voz, args.rate, destino))
        except Exception as e:
            print(f"[cena {cid}] ERRO ao gerar audio: {e}")
            continue

        dur = medir_duracao(destino)
        timeline["cenas"].append({
            "id": cid,
            "audio": f"audio/{nome}",
            "duracao_s": dur,
            "imagem": cena.get("imagem"),
            "prompt_movimento": cena.get("prompt_movimento"),
        })
        print(f"[cena {cid}] {nome}  ->  {dur:.2f}s")

    timeline_path = ENTRADA / "timeline.json"
    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

    total = sum(c["duracao_s"] for c in timeline["cenas"])
    print(f"\nTimeline salva: {timeline_path}")
    print(f"Total de cenas com audio: {len(timeline['cenas'])} | duracao total: {total:.2f}s")
    print("\nProximo passo: usar as duracoes do timeline.json para gerar os clipes no Wan.")


if __name__ == "__main__":
    main()
