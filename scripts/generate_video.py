#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_video.py — Cliente LOCAL que dispara a geração dos clipes no Modal.

Le entrada/roteiro.json (e, se existir, entrada/timeline.json com as duracoes
dos audios), envia cada cena para o Modal (Wan 2.1 na A100) e baixa os clipes
para saida/cenas/cena_XX.mp4.

O modelo e carregado UMA vez no Modal (classe WanRunner) e todas as cenas sao
geradas na mesma ligada da GPU -> mais rapido e barato que 1 ligada por cena.

Uso (do seu terminal, na pasta do projeto):
  modal run scripts/generate_video.py

Opcional:
  modal run scripts/generate_video.py --steps 30 --fps 16

Observacao: a duracao de cada cena vem do timeline.json (duracao do audio) se
disponivel; senao, usa 'duracao_s' do roteiro.json (padrao 5s).
"""

import json
import pathlib
import sys

import modal

# Importa o app e os componentes já definidos em modal_app/app.py
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from modal_app.app import app, WanRunner, montar  # noqa: E402

BASE = pathlib.Path(__file__).resolve().parent.parent
ENTRADA = BASE / "entrada"
SAIDA = BASE / "saida" / "cenas"


def carregar_cenas():
    """Monta a lista de cenas com bytes da imagem e duracao (do timeline se houver)."""
    roteiro_path = ENTRADA / "roteiro.json"
    if not roteiro_path.exists():
        print(f"[ERRO] roteiro nao encontrado: {roteiro_path}")
        sys.exit(1)
    roteiro = json.loads(roteiro_path.read_text(encoding="utf-8"))

    # Duracoes do timeline (audio), se existir: {id -> (duracao_s, audio_rel)}
    duracoes = {}
    audios = {}
    timeline_path = ENTRADA / "timeline.json"
    if timeline_path.exists():
        tl = json.loads(timeline_path.read_text(encoding="utf-8"))
        for c in tl.get("cenas", []):
            if c.get("duracao_s"):
                duracoes[c["id"]] = c["duracao_s"]
            if c.get("audio"):
                audios[c["id"]] = c["audio"]
        print(f"timeline.json encontrado: {len(duracoes)} duracao(oes), {len(audios)} audio(s).")

    cenas = []
    for c in roteiro.get("cenas", []):
        cid = c.get("id")
        img_rel = c.get("imagem")
        if not img_rel:
            print(f"[cena {cid}] sem 'imagem' — pulando.")
            continue
        img_path = ENTRADA / img_rel
        if not img_path.exists():
            print(f"[cena {cid}] imagem nao encontrada: {img_path} — pulando.")
            continue
        dur = duracoes.get(cid, c.get("duracao_s", 5.0))

        # bytes do audio da cena (se houver)
        audio_bytes = None
        audio_rel = audios.get(cid)
        if audio_rel:
            apath = ENTRADA / audio_rel
            if apath.exists():
                audio_bytes = apath.read_bytes()
            else:
                print(f"[cena {cid}] audio listado mas nao encontrado: {apath}")

        cenas.append({
            "id": cid,
            "imagem_bytes": img_path.read_bytes(),
            "prompt": c.get("prompt_movimento", ""),
            "duracao_s": float(dur),
            "seed": int(c.get("seed", 0)),
            "audio_bytes": audio_bytes,
        })
        print(f"[cena {cid}] {img_rel}  dur={dur}s  audio={'sim' if audio_bytes else 'nao'}")
    if not cenas:
        print("[ERRO] nenhuma cena valida no roteiro.")
        sys.exit(1)
    return roteiro, cenas


@app.local_entrypoint()
def main(steps: int = 40, fps: int = 16, guidance: float = 5.0, montar_final: bool = True):
    roteiro, cenas = carregar_cenas()
    print(f"\nEnviando {len(cenas)} cena(s) para o Modal (Wan 2.1 / A100)...")
    print(f"Parametros: steps={steps} fps={fps} guidance={guidance}\n")

    # Payload de GERAÇÃO (só o que o Wan precisa; sem audio).
    cenas_gen = [
        {k: c[k] for k in ("id", "imagem_bytes", "prompt", "duracao_s", "seed")}
        for c in cenas
    ]

    runner = WanRunner()
    resultados = runner.gerar_lote.remote(
        cenas_gen, fps=fps, guidance_scale=guidance, num_inference_steps=steps
    )

    # Salva os clipes individuais (backup / inspeção).
    SAIDA.mkdir(parents=True, exist_ok=True)
    videos_por_id = {}
    for r in resultados:
        cid = r["id"]
        videos_por_id[cid] = r["video_bytes"]
        out = SAIDA / f"cena_{int(cid):02d}.mp4"
        out.write_bytes(r["video_bytes"])
        print(f"OK cena {cid} -> {out}  ({len(r['video_bytes'])/1024:.0f} KB)")

    if not montar_final:
        print(f"\nClipes salvos em {SAIDA}. Montagem desativada (--montar-final False).")
        return

    # --- Montagem no Modal (CPU): une clipes (na ordem do roteiro) + narração ---
    print("\nMontando video final no Modal (CPU + ffmpeg)...")
    ordem_ids = [c["id"] for c in cenas]  # ordem do roteiro
    audio_por_id = {c["id"]: c.get("audio_bytes") for c in cenas}
    cenas_montagem = [
        {"id": cid, "video_bytes": videos_por_id[cid], "audio_bytes": audio_por_id.get(cid)}
        for cid in ordem_ids if cid in videos_por_id
    ]
    final_bytes = montar.remote(cenas_montagem, largura=1080, altura=1920, fps=24)

    saida_final = BASE / "saida" / f"{roteiro.get('titulo', 'video')}_final.mp4"
    saida_final.write_bytes(final_bytes)
    print(f"\nVIDEO FINAL -> {saida_final}  ({len(final_bytes)/1024:.0f} KB)")
    print(f"Clipes individuais tambem em: {SAIDA}")
