# Videos_virais

Pipeline de geração de vídeos curtos (formato viral 9:16) usando GPU sob demanda
na nuvem (Modal), com cobrança por segundo de uso.

## Visão geral da linha de produção

```
LOCAL (você)                                MODAL (nuvem, GPU serverless)
────────────────                            ──────────────────────────────
1. Roteiro (ChatGPT) ─────┐
2. Imagens dos            │
   personagens           ─┤─── upload ───►   Volume persistente (modelo já baixado)
   (Nano Banana)          │                        │
   -> pasta entrada/      │                   função GPU (I2V):
                          │                     - carrega modelo de vídeo
                          │                     - gera 1 clipe por cena
                          │                     - (opcional) narração TTS
                          │                     - monta vídeo final (ffmpeg)
                          │                        │
                          └◄──── download ──── saida/video_final.mp4
```

Vantagem sobre a tentativa anterior (Kaggle T4): a GPU da nuvem tem VRAM
suficiente (48-80 GB) para rodar os modelos bons em fp16 sem offload, e o
modelo fica em cache num Volume — não rebaixa a cada execução. Você paga só
pelo tempo real de geração.

## Estrutura de pastas

```
Videos_virais/
├── README.md                # este arquivo
├── audio_generator.py       # gera narrações (edge-tts) local + timeline.json
├── entrada/                 # VOCÊ coloca aqui (roteiro + imagens)
│   ├── roteiro.json         # cenas, prompts de movimento, narração
│   ├── timeline.json        # gerado: id, áudio, duração por cena
│   ├── audio/               # gerado: cena_XX.mp3 (narrações)
│   └── imagens/             # personagens gerados no Nano Banana (.png)
├── saida/                   # vídeos gerados baixam aqui
│   └── cenas/               # clipes individuais (backup/inspeção)
├── modal_app/               # código que roda no Modal (GPU)
│   └── app.py               # Volume + WanRunner (I2V) + montar (ffmpeg)
└── scripts/                 # utilitários locais (upload, run, download)
    └── generate_video.py    # lê roteiro/timeline -> Modal -> baixa mp4
```

## Formato do roteiro (proposta — a confirmar)

`entrada/roteiro.json`:
```json
{
  "titulo": "meu_video",
  "formato": "9:16",
  "fps": 24,
  "cenas": [
    {
      "id": 1,
      "imagem": "imagens/personagem1.png",
      "prompt_movimento": "the character slowly looks up and smiles, gentle camera push-in",
      "duracao_s": 5,
      "narracao": "Texto que será narrado nesta cena."
    },
    {
      "id": 2,
      "imagem": "imagens/personagem2.png",
      "prompt_movimento": "the character raises a hand and waves, subtle motion",
      "duracao_s": 5,
      "narracao": "Segunda fala da narração."
    }
  ]
}
```

## Decisões técnicas (V1 — TRAVADAS)

| Item | Escolha |
|------|---------|
| Plataforma de GPU | Modal (serverless, cobrança por segundo) |
| GPU | **A100 80GB** (reaproveitável para vários vídeos) |
| Modelo de vídeo (I2V) | **Wan 2.1 14B I2V** (variante I2V-14B-480P) |
| Narração | **Em off** (voz over) — edge-tts rodando LOCAL, sem GPU |
| Lip-sync | **NÃO na V1** (personagem não fala na tela) |
| Montagem final | ffmpeg — feita DEPOIS (áudio já pronto local) |
| API HTTP | **NÃO na V1** — dispara via `modal run` direto |
| ComfyUI | **NÃO na V1** — diffusers puro; avaliar depois p/ mais controle |

Importante: o Wan 2.1 NÃO faz sincronização labial. Lip-sync (se um dia o
personagem precisar falar na tela) é uma etapa separada com modelos próprios
(LatentSync/Wav2Lip), planejada só para uma V1.5 futura.

## Ordem do áudio (importante)

A narração é gerada PRIMEIRO, localmente (edge-tts, sem GPU), porque a duração
do áudio define a duração do clipe de vídeo. Fluxo:
1. Texto da cena -> edge-tts (local) -> `cena_XX.mp3` + duração medida.
2. Wan gera o clipe com a duração correspondente.
3. ffmpeg junta vídeo + narração (etapa de montagem, depois).

## Plano de implementação (V1)

```
FASE A — Setup
  - Estrutura local (feito).
  - pip install modal  ->  modal token new  (autenticação).
  - modal_app/app.py: Volume persistente.

FASE B — Provar o Wan 2.1 I2V no Modal (núcleo)
  - Baixar Wan 2.1 I2V-14B-480P para o Volume (UMA vez).
  - Teste I2V: imagem (Nano Banana) + prompt -> clipe 5s.
  - Medir tempo + VRAM + custo real na A100.

FASE C — Disparo local
  - scripts/generate_video.py: lê roteiro.json + imagens -> Modal -> baixa mp4.

FASE D — Áudio (local) e montagem (depois)
  - audio_generator.py (edge-tts) gera narrações + timeline.json.
  - ffmpeg concatena cenas + áudio no final.

V2 (em andamento) — ComfyUI local orquestrando + GPU no Modal (ver abaixo).
V3 (futuro) — agentes/automação e lip-sync (LatentSync/Wav2Lip).
```

## V2 — ComfyUI local orquestrando + GPU no Modal (DECIDIDO)

Objetivo: usar o ComfyUI **instalado na máquina local** como painel de controle
visual (organizar imagens de referência, roteiro, locução e prompts), e disparar
a geração pesada de vídeo no Modal (A100), que **acorda sob demanda e desliga logo
depois**. Uso no dia a dia sem abrir VS Code.

### Por que este desenho (e não ComfyUI inteiro no Modal)

O ComfyUI é um processo único: a UI (navegador) fala com um backend Python que
precisa da GPU. Não dá para separar "UI local" de "GPU remota" de forma nativa —
os nós de sampling rodam no mesmo processo do backend. As opções eram:

- **A) ComfyUI inteiro no Modal, UI no navegador local.** Funciona, mas a A100
  fica de pé (e faturando) o tempo TODO em que a UI está aberta, mesmo ociosa.
  Rejeitada por custo.
- **B) ComfyUI local só organiza; vídeo é gerado no Modal por chamada.** ← ESCOLHIDA.
  A GPU só liga no instante do render e desliga sozinha. Custo de batch, igual ao
  `app.py` atual. É o melhor custo-benefício.
- **C) ComfyUI local com GPU local.** Descartada (VRAM insuficiente — foi o motivo
  de abandonar o Kaggle T4).

### Divisão de trabalho (leve = local, pesado = Modal)

```
PC LOCAL (ComfyUI, SEM GPU forte — só organiza)      MODAL (A100 só no clique)
──────────────────────────────────────────────      ──────────────────────────
- imagens de referência                              nó "Gerar no Modal":
- roteiro (cenas, prompts de movimento)   ── pacote ─► - acorda a A100
- locução edge-tts -> timeline.json          (imgs +   - WanRunner.gerar_lote
- monta o "pacote" da geração                roteiro + - montar (ffmpeg 9:16)
                                             áudios)   - GPU desliga sozinha
                                                    ◄── mp4 pronto ───
```

Os nós de organização são CPU/IO (não precisam de GPU). O passo de vídeo é um
**nó customizado** do ComfyUI que **chama a função Modal** já existente
(`modal_app/app.py` → `WanRunner.gerar_lote` + `montar`). O ComfyUI NÃO terceiriza
um KSampler para o Modal; ele apenas dispara a função remota e recebe o mp4. Não há
preview do vídeo sendo sampleado ao vivo — chega o mp4 pronto quando o Modal termina.

### Controle de custo da A100 (freios OBRIGATÓRIOS)

A A100 só deve faturar durante o render. Freios a embutir no app Modal:

| Freio | Valor | Para quê |
|-------|-------|----------|
| `scaledown_window` | curto (~120s) | derruba o container após ociosidade → para de cobrar |
| `timeout` | 1–2h | trava de segurança: nunca fica ligado além disso |
| `max_containers` | 1 | nunca sobe várias A100 em paralelo por engano |
| `modal app stop` | manual | encerrar explicitamente ao terminar |

Consequência aceita: quando a GPU dorme, a PRÓXIMA geração recarrega o Wan (alguns
segundos a ~1-2 min). É o preço de não pagar GPU parada — comportamento desejado.

### Modelo de uso (dia a dia)

| Tarefa | Precisa de VS Code? |
|--------|---------------------|
| Gerar vídeo no dia a dia | Não — só ComfyUI no navegador (`localhost:8188`) → Queue Prompt |
| Iniciar o ComfyUI | Não é VS Code, mas é "ligar o ComfyUI" (ícone/comando) |
| Autenticar o Modal (`modal token new`) | Uma vez só; só repete se o token expirar |
| Mudar parâmetros/modelo/lógica do script | Sim — aí sim mexer no código |

### Plano de implementação (V2)

```
FASE V2-A — Instalar ComfyUI local (em andamento pelo usuário)
  - Confirmar: caminho da instalação + tipo (Desktop .exe ou manual/portable).
  - Localizar a subpasta custom_nodes/.

FASE V2-B — Nó customizado "Videos Virais -> Gerar no Modal"
  - Criar ComfyUI/custom_nodes/videos_virais/ que chama modal_app/app.py.
  - Reaproveita Volume + WanRunner + montar já existentes.
  - Requer Modal autenticado na máquina (modal token new — uma vez).

FASE V2-C — Grafo no ComfyUI
  - imagem -> prompt_movimento -> áudio (edge-tts) -> nó "Gerar no Modal" -> mp4.
  - Queue Prompt: acorda A100, gera lote, monta, baixa; GPU desliga sozinha.
```

Recomendação registrada: validar primeiro o fluxo ponta a ponta como comando único
(reusando `audio_generator.py` + `scripts/generate_video.py`) e SÓ DEPOIS empacotar
como nó de ComfyUI, para não travar na criação do nó antes de provar o essencial.

### Custom node — IMPLEMENTADO (como instalar e usar)

O node vive DENTRO do projeto (versionado junto), em:
```
custom_nodes/videos_virais/
├── __init__.py       # expõe os nós ao ComfyUI
├── nodes.py          # lógica: dispara o Modal via subprocesso
└── pyproject.toml    # metadados (ComfyUI Manager)
```

Ele NÃO importa `modal` dentro do ComfyUI. Em vez disso, dispara um subprocesso
chamando o Python global da máquina (que tem `modal` instalado e autenticado):
`C:\Python313\python.exe -m modal run scripts/generate_video.py [args]`. Assim a
`.venv` isolada do ComfyUI Desktop não é tocada.

Ambiente desta máquina (verificado):
- ComfyUI **portable**: `C:\ComfyUI\` (`.bat` de inicialização) e código em
  `C:\ComfyUI\ComfyUI\`. Python embarcado em `C:\ComfyUI\python_embeded\python.exe`.
  (A versão Desktop foi ELIMINADA — dava problema de reinstalação; ver histórico.)
- GPU Intel → não roda Wan 14B local; inicie com `run_cpu.bat` (o ComfyUI só
  organiza e dispara o Modal, então CPU basta).
- Python global com Modal autenticado: `C:\Python313\python.exe`.
- Volume `videos-virais-modelos` já contém o Wan 2.1 I2V-14B-480P completo.

Instalação no ComfyUI (feita via junction — reflete edições automaticamente):
```
mklink /J "C:\ComfyUI\ComfyUI\custom_nodes\videos_virais" "C:\Users\Taty\Desktop\Videos_virais\custom_nodes\videos_virais"
```
(alternativa: copiar a pasta `custom_nodes/videos_virais/` para dentro do
`custom_nodes/` do ComfyUI — mas aí precisa recopiar a cada edição.)

Os dois nós (categoria "Videos Virais" no menu do ComfyUI):
1. Config (projeto + Python) — já vem com os caminhos autodetectados.
2. Gerar no Modal (A100) — parâmetros steps/fps/guidance/montar_final.
   Ligue a saída `config` do nó 1 na entrada `config` do nó 2. Saídas do nó 2:
   `caminho_mp4` (caminho do vídeo final) e `log` (saída do Modal).

Fluxo de uso no dia a dia:
1. Coloque imagens em `entrada/imagens/` e edite `entrada/roteiro.json`.
2. (Locução) rode `python audio_generator.py` para gerar áudios + `timeline.json`.
   (Isso ainda é fora do ComfyUI nesta versão; pode virar um nó depois.)
3. Abra o ComfyUI (`localhost:8188`), monte o grafo Config → Gerar no Modal.
4. Queue Prompt: o node acorda a A100, gera, monta, baixa o mp4 em `saida/`, e a
   GPU do Modal desliga sozinha. O caminho do arquivo aparece na saída do nó.

Pré-requisito único (uma vez): Modal autenticado na máquina (`modal token new`).
Nesta máquina já está autenticado (profile `marconijs`).

## V-futuro — avaliar upgrade de modelo (registrado)

O V1 usa **Wan 2.1 I2V-14B-480P** (open source, Alibaba), já instalado no Volume e
validado. Pesquisa de mercado (2025/2026) indica que ele foi SUPERADO pela própria
sequência e por concorrentes open source. Quando fizer sentido dar upgrade de
qualidade, avaliar:

| Candidato | Destaque | VRAM aprox. | Observação |
|-----------|----------|-------------|------------|
| **Wan 2.2** (Alibaba) | Melhor da familia estavel; fotorrealismo superior | ~27 GB | Mesma linhagem do 2.1 → migração pequena no `app.py`. A100 80GB sobra. Upgrade SEGURO. |
| **Wan 2.7** (Alibaba/Tongyi) | 4 modos num só: T2V + I2V + reference-to-video + video-to-video/edicao + audio nativo. Open-weight Apache 2.0. Suporte no ComfyUI. | A CONFIRMAR | CANDIDATO FORTE: pesos ABERTOS (roda no Modal) e pode UNIFICAR Rumo A e B num modelo so. Falta confirmar se cabe na A100 80GB. |
| **Wan 3.0** (Alibaba) | Flagship: 1080p, clipes 30s, audio nativo, multi-referencia | >80 GB provavel | ARRISCADO: fontes DIVERGEM se os pesos sao abertos (uma diz "zero public weights" = so API) e pode NAO caber em 80GB. Verificar os DOIS antes. |
| **HunyuanVideo 1.5** (Tencent) | Melhor qualidade/VRAM; roda em placa menor | ~14 GB | Poderia até baratear a GPU. |
| **LTX-2 / LTX-2.5** (Lightricks) | Mais rápido, clipes longos, gera áudio junto | varia | Muda o pipeline (áudio nativo). |

Notas:
- **Seedance (ByteDance)** é FECHADO/proprietário (só via API paga) — nunca roda no
  nosso Modal; serve só como referência de qualidade a mirar. Specs de uma suposta
  "Seedance 2.5" não confirmadas (fontes documentam Seedance 1.0, menção a 2.0).
- Nenhum open source empata 100% com os fechados top (Seedance/Sora/Veo/Kling), mas
  Wan 2.2/2.7 e LTX-2.x já são descritos como rivalizando com Sora/Veo em realismo.
- **Wan 2.7 vs 3.0:** o 2.7 é open-weight CONFIRMADO (Apache 2.0) → roda no Modal e
  unifica I2V + motion transfer + swap + audio num modelo so; o 3.0 tem pesos
  DUVIDOSOS (pode ser só API) e provavelmente exige >80 GB. Para A100 80GB + pesos
  abertos: 2.2 = alvo seguro, 2.7 = alvo ambicioso (confirmar VRAM), 3.0 = observar.
- Recomendacao: manter Wan 2.1 por ora (instalado + validado); upgrade seguro = Wan
  2.2; upgrade ambicioso = Wan 2.7. Confirmar VRAM real na A100 antes de 2.7/3.0.

### Dois rumos futuros (DECIDIDO fazer após validar a config atual)

Há dois caminhos DIFERENTES de evolução, com esforço bem distinto:

**Rumo A — Upgrade de qualidade (fácil):** trocar Wan 2.1 I2V → **Wan 2.2 I2V** base.
Mesmo caso de uso (imagem parada + prompt de texto → vídeo; o modelo INVENTA o
movimento). Migração pequena no `app.py`. A100 80GB sobra.

**Rumo B — Novas capacidades (projeto à parte):** adicionar variantes que usam um
VÍDEO de referência para COPIAR movimento:
- **Wan 2.2 VACE** — video-to-video / reference-to-video: anima uma imagem seguindo
  o movimento/pose de um vídeo (motion transfer, dança).
- **Wan 2.2 Animate** — transfere movimento + expressões faciais (com lip-sync) de um
  "driving video" para um personagem; o modo **Replace** faz character/object SWAP
  (troca a pessoa do vídeo pelo seu personagem, mantendo movimento e cenário).

Diferença crítica: o I2V atual NÃO usa vídeo de referência (inventa o movimento do
texto). VACE/Animate USAM um vídeo de referência (copiam o movimento). São MODELOS
DIFERENTES no Volume + pipeline novo no `app.py` + entrada de vídeo grande (subir
para o Volume, não mandar embutido na chamada). Muito útil para "vídeos virais"
(pegar uma trend/dança e colocar o personagem).

Plano: modelos separados no Volume, chamados sob demanda conforme o caso de cada
vídeo (I2V puro / motion transfer / swap).

### Estratégia de armazenamento (custo do Volume) — DECIDIDO

Storage do Modal é custo FIXO mensal (~US$ 0,15/GB/mês de referência — CONFIRMAR
valor atual no pricing), cobrado tenha ou não geração. Cada modelo 14B ocupa ~35 GB
(~US$ 5/mês cada). Download roda em CPU (sem A100), rápido e baratíssimo: ~3–10 min
por modelo (banda HF↔Modal), custo desprezível.

Matemática: 35 GB residente ≈ US$ 0,0073/hora (~1 centavo/h). Só compensa excluir e
rebaixar se o modelo for de uso RARO (o storage economizado supera o incômodo do
download só após muitos dias parado).

Estratégia HÍBRIDA adotada:
- **Wan 2.2 I2V (uso frequente, "pão com manteiga"):** deixar RESIDENTE no Volume
  (~US$ 5/mês). Sem espera de download no dia a dia.
- **Wan 2.2 VACE / Animate (uso ocasional — trends/dança/swap):** baixar SOB DEMANDA
  quando for gerar aquele tipo de vídeo, e EXCLUIR depois. Storage zero para eles;
  paga-se apenas ~3–10 min de download na hora do uso.

Comparativo de custo mensal de storage:
- Só Wan 2.1 hoje (~35 GB): ~US$ 5/mês.
- Os 3 modelos residentes (~120 GB): ~US$ 18/mês.
- Híbrido (I2V residente + VACE/Animate sob demanda): ~US$ 5/mês. ← escolhido.

Implementação futura no `app.py` (Rumo B): parametrizar `download_model` por modelo
e adicionar `delete_model` (o `download_model` atual já é ~90% disso). Assim dá para
gerenciar "baixar/usar/excluir" sob demanda sem mexer em código a cada vez.

NÃO fazer agora: só ao iniciar o Rumo B (após validar a config atual). Até lá, fica
só o Wan 2.1 residente.

## Laboratório de aprendizado — ComfyUI + Flux no Kaggle (GRÁTIS)

Ambiente de TREINO paralelo, separado do Modal, para aprender o PROCESSO do ComfyUI
(montar workflow, nós, sampler, prompts) gerando IMAGENS com Flux na GPU T4 grátis
do Kaggle. A lógica aprendida transfere quase inteira para o vídeo (Wan) no Modal.

Por que Kaggle e não local nem Modal:
- PC local tem GPU Intel → não roda modelos pesados; serve só para a interface.
- Modal (A100) é caro para os MUITOS testes do aprendizado.
- Kaggle dá 2x T4 (16 GB cada, usa 1) GRÁTIS (~30h/semana) → ótimo para treinar
  com Flux FP8 (imagem). NÃO roda Wan 14B (T4 pequena) — vídeo continua só no Modal.

Como funciona (arquitetura): o ComfyUI roda DENTRO do notebook Kaggle (backend +
T4), e você acessa a interface pelo navegador via túnel cloudflared. É "hospedado
no Kaggle, operado do seu navegador". NÃO dá para o ComfyUI local usar a T4 remota
(o ComfyUI não separa UI de GPU; e o Kaggle, ao contrário do Modal, não expõe função
remota chamável por código).

Arquivos do laboratório (neste projeto):
- `kaggle_comfyui_flux.md` — guia passo a passo, célula por célula (didático).
- `kaggle_setup_unico.md` — UMA célula que faz tudo (ComfyUI + Manager + Flux FP8 +
  túnel), idempotente. Uso no dia a dia. Troque o HF_TOKEN antes de rodar.
- `kaggle_setup.py` — MESMO setup como script Python (ComfyUI + Manager + Flux +
  epiCRealism + túnel). RECOMENDADO: evita erro de copy-paste no Kaggle.

### Forma recomendada de rodar (via GitHub — sem copiar código longo)

O projeto está versionado no GitHub: **https://github.com/marconi2/Videos_virais**
(público). O `kaggle_setup.py` é baixado e executado por UMA linha curta, então você
nunca cola código grande no Kaggle (o que causava SyntaxError/IndentationError).

No Kaggle (GPU T4 x2 + Internet On), apenas DUAS células curtas:

Célula 1 (tokens — ficam só no Kaggle, nunca no GitHub):
```
import os
os.environ["HF_TOKEN"] = "hf_seu_token_aqui"
os.environ["CIVITAI_TOKEN"] = "sua_chave_civitai_aqui"
```

Célula 2 (baixa e roda o setup):
```
!wget -q https://raw.githubusercontent.com/marconi2/Videos_virais/main/kaggle_setup.py -O setup.py && python setup.py
```

Ciclo de manutenção: para mudar o setup (novo modelo/node), edita-se `kaggle_setup.py`
no projeto → commit + push → no Kaggle roda a MESMA linha (pega a versão nova). Os
tokens nunca vão para o repositório (lidos de `os.environ`).

Modelos configurados no script: Flux FP8 (`Comfy-Org/flux1-dev`) e epiCRealism
(Civitai modelVersionId 143906, SD 1.5). Cada workflow usa o modelo compatível com
sua arquitetura (workflow Flux usa Flux; workflow SD 1.5 usa epiCRealism — NÃO são
intercambiáveis no mesmo grafo).

Pré-requisitos: conta Kaggle com telefone verificado (libera GPU); token de leitura
do HuggingFace; aceitar a licença do FLUX.1-dev no HF (uma vez).

Limitação-chave do Kaggle: `/kaggle/working` é APAGADO ao desligar a sessão E tem
só ~20 GB. Modelos grandes não cabem nem persistem ali.

SOLUÇÃO ADOTADA (implementada e funcionando) — Kaggle Dataset:
- Modelos ficam num **Kaggle Dataset** (`comfyui-models`), montado em `/kaggle/input/`
  — PERSISTENTE, fora dos 20 GB do working, read-only, carrega instantâneo.
- O `kaggle_setup.py` DETECTA o Dataset automaticamente (procura a pasta `checkpoints`
  dentro de `/kaggle/input`, independente do caminho exato) e gera um
  `extra_model_paths.yaml` apontando o ComfyUI para lá. Modelos aparecem no Load
  Checkpoint SEM ocupar o working.
- Estrutura dentro do Dataset: `checkpoints/`, `loras/`, `vae/`, `clip/`, `unet/`,
  `controlnet/`, `upscale_models/` (uma pasta por tipo).
- Tokens (`HF_TOKEN`, `CIVITAI_TOKEN`) ficam nos **Secrets do Kaggle** (Add-ons >
  Secrets), lidos via `UserSecretsClient` — nunca em célula nem no GitHub.
- Validado: epiCRealism no Dataset → ComfyUI lê de lá, working livre.

Para ADICIONAR modelos: baixar numa estrutura `comfyui-models/<tipo>/arquivo` e
atualizar o Dataset (New Version ou Notebook Output). O script detecta sozinho.

Modelo de aprendizado: epiCRealism (SD 1.5, ~2 GB) no Dataset. Para Flux FP8
(~17 GB) e outros grandes, mesma estratégia (Dataset). Wan 14B de vídeo NÃO roda na
T4 — continua só no Modal.

## Laboratório de aprendizado 2 — ComfyUI interativo na T4 do Modal (DECIDIDO/ATUAL)

Após o ban do Kaggle (conteúdo NSFW de um prompt sem negative), migramos o
aprendizado para o **Modal**, usando os **US$ 30/mês de crédito grátis**. Vantagens:
sem risco de ban por conteúdo (Modal é infra, não policia como o Kaggle); mesmo
ambiente da produção; Volume persistente (modelos não rebaixam).

Arquivo: `modal_app/comfyui.py` — ComfyUI INTERATIVO na T4 via `@modal.web_server(8188)`.

CUSTO (entender bem): aqui o ComfyUI roda DENTRO da T4 (~US$ 0,59/h), então paga-se
a GPU o TEMPO TODO que a UI está aberta (montando workflow, pensando, gerando), NÃO
só na geração. US$ 30 ÷ 0,59 ≈ ~50h/mês. Freios embutidos: `scaledown_window=60`
(cai 60s após ociosidade), `timeout=3600` (máx 1h/sessão), `max_containers=1`.
DISCIPLINA: fechar e `modal app stop` ao terminar.

Dica para esticar o crédito: montar/entender workflows no ComfyUI LOCAL (PC, grátis)
e usar a T4 do Modal só quando for realmente gerar.

Uso:
```
# 1) criar o Secret do Civitai no Modal (uma vez):
modal secret create civitai CIVITAI_TOKEN=sua_chave_civitai

# 2) baixar o epiCRealism para o Volume (uma vez; CPU, barato):
modal run modal_app/comfyui.py::download_epicrealism

# 3) subir o ComfyUI interativo (abre uma URL web):
modal serve modal_app/comfyui.py

# 4) ao terminar, DESLIGAR (nao faturar parado):
modal app stop comfyui-aprendizado
```

Modelos ficam no Volume `videos-virais-modelos`, subpasta `/vol/comfyui/<tipo>/`
(checkpoints, loras, vae, ...). O ComfyUI lê de lá via `extra_model_paths.yaml`.
GPU trocável para L4 (24 GB, ~US$ 0,80/h) quando testar Flux (T4 fica apertada).

NOTA sobre multiplas contas: usar APENAS 1 conta Modal (os termos proíbem múltiplas
contas para ganhar mais crédito; risco de perder a conta principal com o projeto).
Se os US$ 30 acabarem, plano B = Lightning AI (80h/mês grátis).

## V-futuro — narração: avaliar F5-TTS PT-BR (registrado)

Hoje a narração usa **edge-tts** (LOCAL, CPU, grátis, vozes prontas da Microsoft —
NÃO clona voz). Candidato de upgrade quando formos trabalhar no Modal:

**F5-TTS** (repo oficial `SWivid/F5-TTS`) — TTS moderno (Diffusion Transformer +
flow matching) com **clonagem de voz zero-shot** (clona uma voz a partir de poucos
segundos de áudio de referência). Um dos TTS open source mais avançados.

Fine-tunes PT-BR (COMUNIDADE, não oficiais — qualidade varia, VERIFICAR na hora):
- `Tharyck/multispeaker-ptbr-f5tts` — multilocutor brasileiro (parece o mais completo).
- `firstpixel/F5-TTS-pt-br`, `fuuuzzy/F5-TTS-pt-br` — pesos PT-BR (alguns "preliminares").
- `ModelsLab/F5-tts-brazilian` — outra variante brasileira.

Diferença crítica de arquitetura (impacto na decisão):
- **edge-tts (atual):** roda LOCAL sem GPU, grátis, mas voz genérica (não clona).
- **F5-TTS:** clona voz (narração personalizada), MAS precisa de GPU → rodaria no
  MODAL, não local. Ou seja, muda o fluxo: a narração deixaria de ser "local sem
  GPU" e passaria a ser mais um passo no Modal (mais VRAM/tempo/custo por vídeo).

Quando avaliar: só se quiser NARRAÇÃO COM VOZ CLONADA/personalizada. Para voz over
genérica, o edge-tts atual já resolve de graça. Decidir custo-benefício na hora
(edge-tts grátis-local vs. F5-TTS melhor-mas-no-Modal).
