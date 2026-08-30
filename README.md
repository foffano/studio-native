# Studio Native

Gera videos verticais curtos com apoio de IA e os envia para o seu TikTok — tudo
no seu computador.

Voce escolhe um video, a IA (via **OpenRouter**) escreve a frase que aparece na
tela, a legenda do post e ate 5 hashtags. O texto e sobreposto **localmente** com
MoviePy + Pillow + ffmpeg. Opcionalmente ha narracao por voz (**ElevenLabs**). No
fim, o video vai para o seu TikTok com um clique.

Roda como um **servico no seu PC**, em segundo plano, e se usa **pelo
navegador** — no proprio computador ou, com um tunel, do celular.

> **Privacidade:** o video **nunca** e enviado a OpenRouter nem a ElevenLabs —
> elas recebem so texto. Na publicacao, o MP4 vai do seu computador **direto**
> para o TikTok, sem passar por servidor intermediario. O unico servico proprio
> que existe (um Cloudflare Worker) guarda o `client_secret` do TikTok e troca
> codigos por token; ele nao recebe, nao armazena e nunca ve nenhum video.

---

## Como instalar

Ate a versao 1.3 isto era um `.exe` do Electron. Nao e mais: virou um servico
que fica de pe no seu PC e se abre pelo navegador. A troca resolveu o problema
que o `.exe` nunca resolveu — usar do celular — e de quebra tirou 600 MB de
Chromium empacotado.

**Precisa uma vez:** Python 3.10+, Node.js 18+ e Git.

```bash
git clone https://github.com/foffano/studio-native.git
cd studio-native
pip install -r requirements.txt
python tools/fetch_ffmpeg.py     # baixa ffmpeg/ffprobe para bin/
cd desktop && npm install && npm run build && cd ..
```

**Deixar rodando em segundo plano:**

```powershell
powershell -ExecutionPolicy Bypass -File tools\instalar-servico.ps1
```

Isso cria uma tarefa no Agendador do Windows que sobe o app quando voce entra na
maquina, sem janela nenhuma. Depois disso o app vive em
**http://127.0.0.1:5050**.

> A tarefa roda **como o seu usuario do Windows**, e isso nao e detalhe: os
> tokens do TikTok sao cifrados com DPAPI, amarrados a sua conta. Como SYSTEM, a
> decifragem falharia e o app pediria para reconectar a conta sem explicar por
> que.

**Na primeira vez que abrir**, o app pede para criar uma senha. E ela que separa
o app do resto da internet quando ha um tunel de pe.

**Atualizar:**

```powershell
powershell -ExecutionPolicy Bypass -File tools\atualizar.ps1
```

Puxa o codigo, reconstroi o front e reinicia o servico. Se o build falhar, o
servico **nao** e reiniciado: continua servindo a versao que funcionava.

### Primeiros passos dentro do app

**1. Coloque a chave da OpenRouter.** Em **Ajustes -> Chaves de API**, cole a
`OPENROUTER_API_KEY`. Sem ela o app nao gera frase nenhuma. Pegue a sua em
[openrouter.ai](https://openrouter.ai/keys).

**2. (Opcional) Narracao por voz.** Ainda em Ajustes, cole a
`ELEVENLABS_API_KEY` e cadastre ao menos uma voz em **Vozes** — nome, Voice ID
e, se quiser, os parametros. Sem voz cadastrada, o modo com narracao fica
indisponivel de proposito.

**3. (Opcional) Conecte o TikTok.** Em **Ajustes -> Conta do TikTok**, clique em
*Conectar TikTok*. Abre o navegador para autorizar, e a tela se atualiza sozinha.
Veja a ressalva sobre o modo sandbox mais abaixo.

**4. Adicione videos a Biblioteca.** E de la que toda producao comeca. Arraste os
arquivos para a area de upload; o app normaliza cada um automaticamente (HDR,
rotacao, `.mov` de iPhone).

**5. Produza.** No card de um video, clique em **Produzir video**, ajuste tema,
numero de variacoes, altura e estilo do texto, e gere.

Seus dados ficam em `%APPDATA%\StudioNative\`: configuracoes, biblioteca, videos
produzidos e o catalogo (`studio.db`).

### Usar pelo celular

O app ja e uma pagina web; falta so um endereco que o telefone alcance.

```bash
cloudflared tunnel --url http://127.0.0.1:5050
```

Abaixo de 720px a interface se reorganiza: a barra lateral vira barra fixa no pe.
Em **Ajustes** ha um QR com o endereco, para nao ter que digitar.

> **Antes de deixar um tunel de pe:** o app pede senha, mas o hostname publico
> aparece nos registros de Certificate Transparency minutos depois de criado, e
> bots os varrem. Proteger com **Cloudflare Access** barra o trafego antes de
> ele chegar nesta maquina. Detalhes em
> [`docs/modo-navegador.md`](docs/modo-navegador.md).

---

## Fluxo de uso

```
Biblioteca  ->  Produzir video  ->  Produzidos  ->  TikTok
 (fontes)       (painel de          (acervo,        (caixa de
                geracao)            metricas)        entrada)
```

**Biblioteca** guarda os videos-fonte, ja normalizados e reutilizaveis. Todo
arquivo entra por aqui.

**Produzir video** e uma subpagina de um video especifico — quando voce chega la,
a fonte ja esta decidida. Ali ficam tema, variacoes, altura da frase, narracao e
estilo do texto.

**Produzidos** e o acervo das saidas, vindo do catalogo em SQLite: contadores de
produzidos/publicados, filtro por estado, busca por frase, legenda, tema ou
hashtag — e o botao de enviar ao TikTok em cada card.

## Publicar no TikTok

O app envia o video para a **Caixa de entrada** do TikTok, nao para o feed. La
voce revisa, adiciona o produto (o "carrinho laranja") e publica.

- **Login** com Login Kit v2 e PKCE, pelo navegador do sistema. Os tokens ficam
  cifrados com o **DPAPI do Windows** — amarrados a sua conta de usuario e
  ilegiveis se o arquivo for copiado para outra maquina. A sessao renova sozinha
  30 minutos antes de vencer.
- **O `client_secret` nao fica neste computador.** Ele mora num Cloudflare Worker
  ([`services/tiktok-auth/`](services/tiktok-auth/)), que faz a troca de token em
  nome do app.
- **O video vai direto** do seu disco para o TikTok, em pedacos. Nenhum servidor
  nosso o recebe.
- **Escopos:** `user.info.basic` (mostrar apelido e avatar da conta de destino) e
  `video.upload` (enviar a caixa de entrada). **Nao** pedimos `video.publish` —
  publicacao direta no feed pularia justamente a etapa em que voce adiciona o
  produto, e puxa a revisao mais rigida do TikTok.

### Onde o video aparece (nao e em Rascunhos)

No celular: TikTok -> aba **Caixa de entrada** -> toque na notificacao do video.
Ele **nao** aparece em Perfil -> Rascunhos: os rascunhos do perfil sao locais do
aparelho, e um video vindo da API nunca vai parar la.

### A legenda nao vai junto — e o que o app faz sobre isso

O endpoint de caixa de entrada aceita **apenas** o arquivo; nao ha campo de
legenda, titulo ou hashtag. Campo de titulo existe so no Direct Post, que e o
caminho que nao usamos.

Entao, depois do envio, o card mostra a legenda com as hashtags e dois caminhos:

- **Copiar legenda** — util se voce finaliza pelo TikTok web.
- **Ler no celular** — um QR code que abre uma **pagina com botao de copiar** no
  telefone. Colar a legenda la e mais rapido do que digitar do zero.

### Modo sandbox

O app esta em **sandbox** no TikTok, aguardando revisao. Na pratica: so contas
cadastradas como *target users* no sandbox conseguem conectar — qualquer outra
recebe `non_sandbox_target`. Todo video enviado fica privado.

Isso nao limita o uso pessoal, e nao ha prazo de validade publicado para o
sandbox. O que tem relogio e a sessao: o refresh token vale 365 dias e e renovado
a cada renovacao, entao usar o app ao menos uma vez por ano mantem a conexao viva.

Material do cadastro e o passo a passo do portal estao em
[`docs/tiktok/formulario-de-cadastro.md`](docs/tiktok/formulario-de-cadastro.md).

---

## Arquitetura

```
   Navegador (PC)          Navegador (celular)
        |                          |
        |                   Cloudflare Tunnel
        |                          |
        +-----------+--------------+
                    |
             Flask em :5050
      serve o React construido E a API,
             na mesma origem
                    |
        app.py + MoviePy + Pillow + ffmpeg
        store.py (SQLite) - tiktok.py - secretbox.py
                    |
        Cloudflare Worker (so troca de token)
        MP4 --> TikTok, direto, sem intermediario
```

- **Frontend:** React (Vite), em `desktop/`. Construido para `desktop/dist/`.
- **Backend:** `app.py` (Flask/MoviePy/ffmpeg/OpenRouter/ElevenLabs), servido por
  **waitress**. Serve tambem o front em `/`, na **mesma origem** — e isso que faz
  funcionar pelo celular, ja que uma URL absoluta com `127.0.0.1` faria o
  telefone tentar conectar nele mesmo.
- **Nao ha shell nativo.** O Electron foi aposentado na 1.4: existia para abrir
  uma janela e subir o backend, e o servico faz as duas coisas melhor. A pasta
  continua chamando `desktop/` por inercia do historico.
- **ffmpeg/ffprobe** ficam em `bin/`, baixados por `tools/fetch_ffmpeg.py`; o
  backend os prioriza sobre os do sistema.
- **Autenticacao:** senha com scrypt e sessao por cookie assinado (`auth.py`).
  Todas as rotas sao privadas por padrao — a lista de excecoes em `PUBLICAS` e
  curta e explicita.
- **Chaves de API** ficam em `%APPDATA%/StudioNative/config.json` (com fallback
  para variaveis de ambiente/`.env`).

## Pré-requisitos de desenvolvimento

- **Node.js 18+** e **Python 3.10+**
- `pip install -r requirements.txt`
- `cd desktop && npm install`
- ffmpeg/ffprobe no PATH **ou** rode `python tools/fetch_ffmpeg.py` para baixá-los em `bin/` (o backend prioriza os binários de `bin/`).

## Rodar em desenvolvimento

Sao dois processos, em dois terminais:

```bash
python app.py                 # backend em :5050
cd desktop && npm run dev     # Vite em :5173, com hot reload
```

Abra **http://127.0.0.1:5173**. O Vite e a unica situacao em que o front e a API
ficam em origens diferentes; e para ela que existe a lista `ORIGENS_PERMITIDAS`
no `app.py`.

Para mexer so no backend, `python app.py` sozinho ja serve o ultimo
`npm run build` em **:5050** — que e exatamente o que roda em producao.

> **Cuidado ao rodar `python app.py` na mao** com o servico ja de pe: os dois
> disputam a porta 5050. O app detecta e recusa subir, em vez de deixar o
> Windows entregar a porta para quem chegou depois.

## Atualizar a instalacao

Nao ha mais instalador nem auto-update: o app roda a partir do repositorio.

```powershell
powershell -ExecutionPolicy Bypass -File tools\atualizar.ps1
```

Puxa o codigo, refaz as dependencias, reconstroi o front e reinicia a tarefa
agendada — nessa ordem, e o reinicio so acontece se o build passou. Se voce
mexeu no codigo localmente e nao quer que ele puxe nada, use `-SemGit`.

## Como funciona (geração)

1. Você adiciona o vídeo à **Biblioteca** (normalizado automaticamente) e clica em **Produzir vídeo**.
2. Escolhe o tema/contexto, quantos vídeos gerar (1 a 10) e a altura/estilo do texto.
3. O backend pede `N` conjuntos à OpenRouter — frase da tela, legenda e hashtags — numa chamada só.
4. Para cada frase, é gerada uma imagem RGBA do texto com Pillow e sobreposta no vídeo com MoviePy.
5. Cada MP4 vira um registro no catálogo e aparece em **Produzidos**, de onde você envia ao TikTok.

## Legenda do post e hashtags

Cada vídeo gerado vem com uma **legenda pronta para o post** e **no máximo 5 hashtags**.
A IA devolve os três textos (frase da tela, legenda e hashtags) **na mesma chamada** da
OpenRouter — a legenda fica coerente com a frase e não custa um segundo request.

O limite e o formato são aplicados no **backend** (`captions.py`), nunca confiando no
prompt: as hashtags perdem o `#`, os espaços e os acentos, viram minúsculas, são
deduplicadas, limitadas a 24 caracteres cada e **cortadas em 5**. Hashtags que a IA
cola no fim da legenda são movidas para a lista em vez de ficarem duplicadas nos dois
lugares. A legenda é normalizada e cortada em 150 caracteres.

Se a IA falhar ou devolver a legenda vazia, entra um **fallback determinístico**: a
legenda vira a própria frase da tela e as hashtags são derivadas do tema digitado mais
as tags do vídeo-fonte na Biblioteca. O usuário nunca fica sem legenda.

No card do resultado a legenda é **editável**, as hashtags viram chips clicáveis (clique
remove) e há um botão **"Outra legenda"** que gera outra sem re-renderizar o vídeo.

## Catálogo de produção (`studio.db`)

Antes, o que o app *produzia* existia só como arquivo solto em `outputs/` mais uma
entrada no `localStorage` do React — o backend não sabia quais vídeos ele mesmo tinha
gerado. Agora cada MP4 renderizado vira um registro em **SQLite**
(`%APPDATA%/StudioNative/studio.db`, módulo `store.py`), com três tabelas:

- **`outputs`** — um registro por vídeo gerado: arquivo, frase, narração, legenda,
  hashtags, tema, vídeo-fonte, duração e data.
- **`publications`** — uma linha por tentativa de publicação (plataforma, conta, modo,
  privacidade, produto, estado, URL do post). Preenchida a partir da integração com o
  TikTok.
- **`accounts`** — contas conectadas.

SQLite em vez de mais um JSON porque os workers de biblioteca, render e publicação
escrevem ao mesmo tempo; o padrão de "lock + reescreve o arquivo inteiro" não aguenta
isso. Vem no Python, sem dependência nova.

Na primeira abertura o app **migra sozinho** o histórico do `localStorage` para o
catálogo (`POST /api/outputs/import`, idempotente, ignora entradas cujo arquivo já não
existe).

**Métricas:** *produzidos* é a contagem de `outputs`; *publicados* conta `output_id`
**distintos** com publicação concluída — um vídeo postado em duas contas é um vídeo
publicado, não dois. Aparecem no topo de **Produzidos**; a Biblioteca mantém só o que é dela — o
número de fontes e quanto cada uma rendeu.

Endpoints: `GET /api/outputs`, `GET/PATCH/DELETE /api/outputs/<id>`,
`POST /api/outputs/<id>/caption`, `POST /api/outputs/import`, `GET /api/metrics`.

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

Antes de entregar o vídeo ao MoviePy, **todo upload passa por uma normalização com ffmpeg** — o binário vai dentro do pacote, então não é preciso tê-lo instalado. Isso evita falhas com arquivos "difíceis" — por exemplo `.mov` de iPhone com HDR/Dolby Vision (HEVC 10-bit), rotação por metadado (display matrix) e várias streams de dados `mebx`. A normalização gera um MP4 "limpo" e padronizado:

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
- **Biblioteca de vozes (ElevenLabs):** em Ajustes › *Vozes* você cadastra várias vozes (nome/apelido + Voice ID + `model_id`/`stability`/`similarity` opcionais). Elas são salvas em `config.json` (chave `voices`) e ficam disponíveis num **seletor** no modo com áudio da aba de geração — sem digitar o Voice ID toda vez. Os parâmetros por voz têm precedência sobre os defaults globais.
- Persistência em `%APPDATA%/StudioNative/config.json` (lido pelo backend). Precedência: **config.json > variáveis de ambiente/.env > default**. As mudanças valem **imediatamente**, sem reiniciar.
- Endpoints: `GET/POST /api/settings`, `GET /api/config`, `GET /api/health`. CORS liberado (o servidor escuta apenas em `127.0.0.1`).
- Dados de usuário (uploads/outputs/config) ficam em `%APPDATA%/StudioNative/` — fora do bundle, gravável.

## Estrutura do repositório

```
app.py                       # backend Flask: OpenRouter/ElevenLabs + MoviePy/Pillow/ffmpeg
                             #   + rotas do TikTok, fila de publicacao e o front construido
store.py                     # catalogo de producao em SQLite (outputs/publications/accounts)
captions.py                  # legenda do post + sanitizacao das hashtags (limite de 5)
tiktok.py                    # Login Kit v2 com PKCE + envio para a caixa de entrada
secretbox.py                 # cifragem dos tokens em repouso (DPAPI no Windows)
auth.py                      # senha (scrypt), sessao por cookie e freio de forca bruta
tools/fetch_ffmpeg.py        # baixa ffmpeg/ffprobe para bin/
tools/instalar-servico.ps1   # cria a tarefa agendada que mantem o app de pe
tools/atualizar.ps1          # git pull + build + reinicio do servico
requirements.txt             # deps Python
fonts/Quicksand.ttf          # fonte arredondada empacotada
bin/                         # ffmpeg.exe/ffprobe.exe (gerado por fetch_ffmpeg.py)

desktop/                     # o front React (o nome sobrou do tempo do Electron)
  package.json               #  scripts npm (dev, build)
  vite.config.js
  index.html
  dist/                      #  saida do build -- e isto que o Flask serve
  src/                       #  React: App, api.js, components/, lib/history.js
  src/components/            #   LibraryView, SourcePanel, FolderTile, ProducedView,
                             #   GenerateView, SettingsView, AuthGate, TikTokAccount,
                             #   PublishToTikTok, CaptionQR, CaptionPage

services/                    # servicos proprios (Cloudflare)
  tiktok-auth/               #  Worker que guarda o client_secret e troca tokens
  studio-site/               #  paginas publicas em studio.toffa.com.br

docs/                        # plano de produto, modo navegador, cadastro no TikTok
```

Saída de build: `desktop/dist/`. Dados em runtime: `%APPDATA%/StudioNative/` — `config.json`, `library.json`, `library/`, `outputs/`, `studio.db` (o catálogo de produção) e `backups/`.

## Documentação

- [`docs/plano-legenda-e-publicacao-tiktok.md`](docs/plano-legenda-e-publicacao-tiktok.md)
  — o roteiro de sete fases. As fases 1 a 5 e a reforma da navegação estão feitas;
  o documento registra também onde a API real desmentiu o plano.
- [`docs/modo-navegador.md`](docs/modo-navegador.md) — rodar no navegador, expor
  por túnel e por que a autenticação pertence ao túnel, não ao código.
- [`docs/tiktok/formulario-de-cadastro.md`](docs/tiktok/formulario-de-cadastro.md)
  — o que preencher no portal do TikTok, com os textos prontos.
- [`services/tiktok-auth/README.md`](services/tiktok-auth/README.md) — o Worker
  de troca de tokens: o que ele faz e, principalmente, o que ele não faz.

### O que falta

- **Revisão do TikTok.** Exige um vídeo de demonstração do fluxo completo, que
  agora é possível gravar. Aprovado, troca-se as credenciais do sandbox pelas de
  produção nos secrets do Worker.
- **Fase 6 — produto no vídeo.** Hoje o carrinho é adicionado à mão no TikTok. A
  Affiliate Creator API permitiria fazer isso pelo app, e exige aprovação separada.
- **MP4 órfãos.** Arquivos antigos em `outputs/` que nunca entraram no catálogo
  ficam fora das métricas e da publicação.
- **MP4 órfãos.** 22 arquivos em `outputs/`, cerca de 65 MB, sem registro no
  catálogo — invisíveis no app e fora de qualquer métrica.
