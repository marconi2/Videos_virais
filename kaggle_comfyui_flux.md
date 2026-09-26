# Kaggle — ComfyUI + Flux FP8 (laboratório de aprendizado GRÁTIS)

Ambiente de TREINO paralelo, separado do Modal. Serve para aprender o PROCESSO do
ComfyUI (montar workflow, conectar nós, sampler, prompts) gerando IMAGENS com Flux.
A lógica que você aprende aqui transfere quase inteira para o vídeo (Wan) no Modal.

NÃO mexe em nada do projeto do Modal (node, app.py, Volume seguem intactos).

## Pré-requisitos (uma vez)

1. Conta no Kaggle com **telefone verificado** (sem isso NÃO libera GPU).
2. No notebook: menu direito → **Accelerator = GPU T4 x2** e **Internet = On**.
3. Aceitar a licença do Flux.1-dev no HuggingFace (uma vez):
   - Acesse https://huggingface.co/black-forest-labs/FLUX.1-dev e clique em aceitar
     os termos (necessário para o download não dar 403). Faça logado na sua conta HF.
   - Gere um token de leitura em https://huggingface.co/settings/tokens
     (guarde-o; você vai colar na Célula 2).

## Como usar

Crie um **novo notebook** no Kaggle (New Notebook), ative GPU T4 x2 + Internet,
e cole cada bloco abaixo em uma célula separada, rodando na ordem.

---

### Célula 1 — Instalar o ComfyUI

```python
import os
# Kaggle costuma dar /kaggle/working como área gravável
os.chdir('/kaggle/working')
!git clone https://github.com/comfyanonymous/ComfyUI
os.chdir('/kaggle/working/ComfyUI')
# Dependências do ComfyUI (o Kaggle ja tem torch com CUDA para a T4)
!pip install -r requirements.txt
print("ComfyUI instalado em /kaggle/working/ComfyUI")
```

---

### Célula 2 — Baixar o Flux FP8 (checkpoint unico, cabe em 16 GB)

```python
# Cole seu token de leitura do HuggingFace aqui:
HF_TOKEN = "coloque_seu_token_aqui"

from huggingface_hub import hf_hub_download
import shutil, os

# Checkpoint FP8 all-in-one (modelo + CLIP + T5 + VAE num arquivo so).
# Repo oficial da Comfy-Org, feito para <24GB VRAM.
arquivo = hf_hub_download(
    repo_id="Comfy-Org/flux1-dev",
    filename="flux1-dev-fp8.safetensors",
    token=HF_TOKEN,
)
destino = "/kaggle/working/ComfyUI/models/checkpoints/flux1-dev-fp8.safetensors"
os.makedirs(os.path.dirname(destino), exist_ok=True)
# hf baixa para cache; copia/linka para a pasta do ComfyUI
if not os.path.exists(destino):
    shutil.copy(arquivo, destino)
print("Flux FP8 pronto em:", destino)
print("Tamanho:", round(os.path.getsize(destino)/1024**3, 1), "GB")
```

---

### Célula 3 — Abrir o tunel (cloudflared) para acessar a UI no navegador

O Kaggle nao expoe porta direto. O cloudflared cria uma URL publica temporaria
que aponta para o ComfyUI rodando no notebook.

```python
# Baixa o cloudflared
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /kaggle/working/cloudflared
!chmod +x /kaggle/working/cloudflared
print("cloudflared pronto")
```

---

### Célula 4 — Iniciar o ComfyUI + tunel (deixe rodando)

```python
passou ja instalei e o comfy ja esta rodando
```

Quando aparecer a URL `https://algo.trycloudflare.com`, abra no seu navegador —
é o ComfyUI rodando na T4 do Kaggle. A célula fica "rodando" (é o servidor vivo);
NÃO pare ela enquanto estiver usando.

---

### Célula 5 (opcional) — Workflow Flux de exemplo

No ComfyUI aberto pela URL:
1. Menu → Workflow → Browse Templates → escolha um template "Flux".
   (ou monte manualmente: Load Checkpoint → CLIP Text Encode (prompt) →
    KSampler → VAE Decode → Save Image)
2. No nó **Load Checkpoint**, selecione `flux1-dev-fp8.safetensors`.
3. Parametros de TESTE (T4 e lenta, entao comece pequeno):
   - steps: 20 (Flux dev funciona bem com 20)
   - resolucao: 1024x1024 (ou 768x768 para ir mais rapido)
   - cfg: 1.0 (Flux usa CFG baixo/guidance embutido)
4. Queue Prompt. Na T4, uma imagem 1024px leva ~1-3 min. Normal (T4 e antiga).

---

## Avisos importantes (custo/limites)

- **Kaggle GPU e GRATIS** mas tem LIMITE (~30h/semana de GPU). Desligue o notebook
  quando nao estiver usando (Stop Session) para nao gastar a cota.
- A URL do cloudflared e TEMPORARIA — muda a cada vez que roda a Célula 4.
- Ao fechar/reiniciar o notebook, o ComfyUI e os modelos somem (o /kaggle/working
  nao persiste entre sessoes por padrao). Voce roda as células de novo. Por isso o
  download do Flux (Célula 2) repete a cada sessao — ~17 GB, leva alguns minutos.
- Dica: para nao rebaixar toda vez, pode-se usar Kaggle Datasets para guardar o
  modelo. Se quiser, peça que eu explico esse passo depois.

## O que isso te ensina para o Modal/Wan

O grafo Flux (imagem) tem a MESMA espinha do Wan (video):
  Load Model -> Encode Prompt -> Sampler (steps/cfg) -> VAE Decode -> Save
No Wan voce troca o modelo, adiciona a imagem de entrada (I2V) e a saida vira
frames em vez de 1 imagem. Montar/conectar/ajustar e igual. Treine aqui de graca.
