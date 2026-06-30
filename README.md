# Studio Native

App **desktop nativo para Windows** (Electron + React) que gera vídeos com IA: você envia um vídeo, a IA (via **OpenRouter**) cria frases curtas de impacto (e, opcionalmente, narração por voz via **ElevenLabs**), e o texto é sobreposto no vídeo **localmente** com **MoviePy** + **Pillow** + **ffmpeg**. Para cada vídeo você escolhe quantas variações (frases diferentes) quer gerar.

> **Privacidade:** o vídeo **nunca** é enviado para a OpenRouter/ElevenLabs. As APIs recebem apenas texto (tema/contexto e a fala). Todo o processamento do vídeo acontece na sua máquina.

## Arquitetura

```
+------------------- Electron (janela nativa) -------------------+
|  React (UI)  <-- HTTP -->  Backend Python (Flask) "sidecar"    |
|  desktop/                  app.py + MoviePy + ffmpeg + Pillow  |
+----------------------------------------------------------------+
```

- **Frontend:** React (Vite), em `desktop/` — recria toda a UI com visual estilo "Studio Native".
- **Shell:** Electron (`desktop/electron/main.cjs`) abre a janela e **inicia o backend Flask** numa porta local livre (loopback), encerrando-o ao fechar.
- **Backend:** o mesmo `app.py` de sempre (Flask/MoviePy/ffmpeg/OpenRouter/ElevenLabs). Em produção é empacotado com **PyInstaller** como executável *sidecar* — o usuário final **não precisa de Python**. O **ffmpeg/ffprobe** é empacotado junto (pasta `bin/`) e resolvido via `sys._MEIPASS` quando "congelado".
- **Chaves de API** são configuradas pela tela **Ajustes** e salvas em `%APPDATA%/StudioNative/config.json` (com fallback para variáveis de ambiente/`.env`). O app funciona sem `.env`.

## Pré-requisitos de desenvolvimento

- **Node.js 18+** e **Python 3.10+**
- `pip install -r requirements.txt`
- `cd desktop && npm install`
- ffmpeg/ffprobe no PATH **ou** rode `python tools/fetch_ffmpeg.py` para baixá-los em `bin/` (o backend prioriza os binários de `bin/`).

## Rodar em desenvolvimento

```bash
# 1) deps Python (uma vez)
pip install -r requirements.txt

# 2) deps do app desktop (uma vez)
cd desktop
npm install

# 3) sobe Vite + Electron + backend Python (python app.py) juntos
npm run dev
```

O `npm run dev` inicia o Vite (porta 5173), aguarda, e abre o Electron — que escolhe uma porta livre, sobe `python app.py` com `STUDIO_PORT`, espera o `/api/health` e carrega a UI. As chaves podem ser inseridas na aba **Ajustes** (ou via `.env` na raiz).

> Para rodar só o backend (modo web legado): `python app.py` e abra `http://127.0.0.1:5050`. A porta vem de `STUDIO_PORT`/`PORT` (default 5050).

## Gerar o instalável (.exe)

O empacotamento tem **duas etapas**: (1) backend Python → executável sidecar com PyInstaller; (2) Electron + React → instalador com electron-builder (que inclui o sidecar como recurso).

```bash
# (a) baixa ffmpeg/ffprobe para bin/ (empacotados no sidecar)
python tools/fetch_ffmpeg.py

# (b) empacota o backend Python como sidecar (gera dist/StudioNativeBackend/)
pip install -r requirements.txt
pyinstaller studio_native_backend.spec --noconfirm

# (c) gera o instalador NSIS + portable (inclui dist/StudioNativeBackend/ via extraResources)
cd desktop
npm install
npm run dist            # instalador NSIS + portable  -> desktop/release/
# ou apenas portable:
npm run dist:portable
```

Saída em `desktop/release/` (ex.: `Studio Native Setup x.y.z.exe` e a versão portable). O ícone do app vem de `desktop/build/icon.ico` (gerado a partir do logo da raiz).

> Em produção, o Electron procura o backend em `resources/backend/StudioNativeBackend.exe`; em dev, roda `python app.py`. Defina `STUDIO_PYTHON` para apontar para um interpretador específico em dev, se necessário.

## Como funciona (geração)

1. Você envia um vídeo e (opcionalmente) digita um tema/contexto.
2. Escolhe quantos vídeos gerar (1 a 10) e a altura/estilo do texto.
3. O backend pede `N` frases diferentes à OpenRouter (somente texto).
4. Para cada frase, é gerada uma imagem RGBA do texto com Pillow e sobreposta no vídeo com MoviePy.
5. Você visualiza, baixa e revê no **Histórico** (persistido localmente).

## Modo com áudio (narração via ElevenLabs)

Além do modo padrão (vídeo só com a frase estática), há um **modo com narração por voz**. Primeiro, abra **Ajustes** e cadastre uma ou mais vozes da ElevenLabs com nome/apelido, **Voice ID**, modelo e parâmetros de voz. Depois, na aba de geração, ligue o toggle **"Gerar áudio (narração por voz)"** e escolha uma das vozes cadastradas.

- **Voz da narração** (obrigatório): selecione uma voz salva em **Ajustes**. O app aplica automaticamente o Voice ID, `Model ID`, `Stability` e `Similarity` configurados nessa voz.
- **Tema / contexto da narração** (opcional): prompt próprio desse modo, separado do tema da frase estática.
- **Avançado:** os campos mostram os parâmetros da voz selecionada para conferência.

Para cada variação, no modo com áudio o backend:

1. Pede à OpenRouter **dois textos coerentes** em JSON (`{"overlay": "...", "speech": "..."}`): a **frase da tela** (overlay) e a **narração** (speech), usando técnicas de vídeos virais de TikTok (hook forte, linguagem direta, curiosidade/retenção, CTA no fim).
2. **Dimensiona a fala pela duração do vídeo + 10s:** mede a duração (ffprobe) e instrui a IA a respeitar um limite de palavras (~`(duração + 10) × 2,5 × 0,85`, com margem de segurança). Como a base é a duração + 10s, a narração costuma ficar um pouco mais longa que o vídeo — nesse caso o **último frame é congelado** (passo 4) e o vídeo final fica ~10s mais longo.
3. Envia **apenas a speech** à ElevenLabs (`POST /v1/text-to-speech/{voice_id}`, header `xi-api-key`) e gera o MP3.
4. **Sincroniza** áudio e vídeo:
   - áudio **mais curto** que o vídeo → fica no início (silêncio no fim);
   - áudio **mais longo** → o **último frame é congelado** para o vídeo durar o tempo do áudio.
5. Monta o vídeo final: vídeo normalizado + frase estática (fonte arredondada, emojis, contorno, altura + jitter, entrelinha) + a narração como **áudio principal** (substitui o áudio original). Saída H.264 + AAC.

Os estados do progresso incluem `gerando roteiro`, `gerando áudio (ElevenLabs)` e `montando vídeo`. Se a `ELEVENLABS_API_KEY` não estiver configurada (ou faltar o Voice ID), o modo retorna um erro claro. O resultado e a narração aparecem nos cards e no histórico.

### Variáveis de ambiente (.env)

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o-mini
# Modo com áudio (opcional):
ELEVENLABS_API_KEY=...
ELEVENLABS_MODEL=eleven_multilingual_v2
PORT=5050
```

## Normalização do upload (ffmpeg)

Antes de entregar o vídeo ao MoviePy, **todo upload passa por uma normalização com ffmpeg** (que já precisa estar no PATH). Isso evita falhas com arquivos "difíceis" — por exemplo `.mov` de iPhone com HDR/Dolby Vision (HEVC 10-bit), rotação por metadado (display matrix) e várias streams de dados `mebx`. A normalização gera um MP4 "limpo" e padronizado:

- **Mapeia apenas vídeo + áudio** (`-map 0:v:0 -map 0:a:0?`), descartando streams de dados (`mebx`/Core Media Metadata).
- **Aplica a rotação fisicamente** (autorotação do ffmpeg) e **zera o metadado** de rotação — o vídeo nunca fica "deitado".
- **Converte HDR/10-bit (Dolby Vision/PQ/HLG) para SDR 8-bit** (`yuv420p`) com tonemap (`zscale` + `tonemap=hable`, saída bt709), evitando cores lavadas/escuras. Há um fallback caso o tonemap não esteja disponível.
- **Limita a altura a 1080p** mantendo a proporção (acelera a renderização de vídeos 4K).
- Saída **H.264 (libx264) + AAC** com `+faststart`.

Se o ffmpeg falhar, o job retorna um erro claro na interface. O arquivo enviado e o normalizado são temporários e apagados ao final.

## Fonte arredondada e emojis coloridos

- O texto usa uma **fonte arredondada empacotada no projeto**: `fonts/Quicksand.ttf` (Google Fonts, instância **SemiBold**). Se o arquivo não existir, há fallback para uma fonte do sistema (Segoe UI / Arial / DejaVu).
- Os **emojis são renderizados coloridos**. O texto é desenhado manualmente com Pillow, combinando a fonte arredondada (texto) com uma **fonte de emoji** (`Segoe UI Emoji` no Windows, ou `Noto Color Emoji`/`Apple Color Emoji`), usando `embedded_color=True` para os glifos de emoji.
- **Fallback seguro:** se não houver fonte de emoji disponível, os emojis são simplesmente omitidos — nunca aparece "tofu" (quadrado) e o restante do texto continua aparecendo normalmente.
- O resultado é composto como `ImageClip` (com máscara de transparência) sobre o vídeo, preservando contorno preto, alinhamento centralizado e quebra de linha (caption).

> A fonte de emoji é detectada no sistema operacional; nem todo emoji existe em todas as fontes. Sequências complexas (ZWJ, ex.: famílias) podem cair em emojis simples dependendo da fonte.

## Altura e jitter automático

- Na interface você define a **altura** da frase arrastando o indicador num mini-preview vertical (9:16). O valor é contínuo: **0% = topo**, **100% = base**, **50% = centro** (padrão). O texto permanece sempre centralizado na horizontal.
- O backend recebe esse valor como `vertical` (0.0 a 1.0) e o `compute_position()` posiciona a frase nessa altura.
- Cada vídeo gerado recebe automaticamente um pequeno **deslocamento aleatório (jitter)** em x e y ao redor da altura escolhida — assim cada variação fica levemente diferente. O texto é sempre mantido dentro do quadro (com margens de segurança). Isso acontece por padrão, sem configuração.

## Estilo do texto

Na seção "Opções de estilo" você pode ajustar tamanho da fonte, FPS, o **espaçamento entre linhas** e as cores do **texto** e do **contorno** — escolhidas por uma paleta de **quadradinhos (swatches)** clicáveis, com opção de **cor personalizada** (color picker nativo). O visual segue o mesmo espírito do `TextClip` do MoviePy (contorno, caption, centralizado), porém renderizado via Pillow para suportar a fonte arredondada e os emojis coloridos.

- **Espaçamento entre linhas (entrelinha):** controlado por um slider, como **multiplicador da altura da linha**. Faixa de `0.8x` a `2.0x`, padrão `1.15x`. Define a distância entre as baselines de linhas consecutivas (inclusive entre linhas quebradas automaticamente pelo caption).

## Configuração / chaves

- Tela **Ajustes** (React) para `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL` e altura máxima de render. As chaves são **mascaradas** na UI.
- **Biblioteca de vozes (ElevenLabs):** em Ajustes › *Vozes* você cadastra várias vozes (nome/apelido + Voice ID + `model_id`/`stability`/`similarity` opcionais). Elas são salvas em `config.json` (chave `voices`) e ficam disponíveis num **seletor** no modo com áudio da aba de geração — sem digitar o Voice ID toda vez. Os parâmetros por voz têm precedência sobre os defaults globais; ainda é possível informar um Voice ID avulso quando não há vozes cadastradas.
- Persistência em `%APPDATA%/StudioNative/config.json` (lido pelo backend). Precedência: **config.json > variáveis de ambiente/.env > default**. As mudanças valem **imediatamente**, sem reiniciar.
- Endpoints: `GET/POST /api/settings`, `GET /api/config`, `GET /api/health`. CORS liberado (o servidor escuta apenas em `127.0.0.1`).
- Dados de usuário (uploads/outputs/config) ficam em `%APPDATA%/StudioNative/` — fora do bundle, gravável.

## Estrutura do repositório

```
app.py                       # backend Flask (sidecar): OpenRouter/ElevenLabs + MoviePy/Pillow/ffmpeg
studio_native_backend.spec   # PyInstaller: empacota o backend + static + fonts + bin/ (ffmpeg)
tools/fetch_ffmpeg.py        # baixa ffmpeg/ffprobe para bin/
requirements.txt             # deps Python (inclui pyinstaller)
fonts/Quicksand.ttf          # fonte arredondada empacotada
static/index.html            # UI web legada (mantida; o app usa o React)
bin/                         # ffmpeg.exe/ffprobe.exe (gerado por fetch_ffmpeg.py)

desktop/                     # app Electron + React
  package.json               #  scripts npm + config electron-builder
  vite.config.js
  index.html
  electron/main.cjs          #  processo main: spawn do backend + janela
  electron/preload.cjs       #  expõe a URL do backend ao React
  build/icon.ico             #  ícone do app (gerado do logo)
  src/                       #  React: App, api.js, components/, lib/history.js
```

Saídas de build: `dist/StudioNativeBackend/` (PyInstaller) e `desktop/release/` (instalador). Dados em runtime: `%APPDATA%/StudioNative/`.
