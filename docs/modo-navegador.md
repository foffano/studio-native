# Modo navegador e acesso pelo celular

O Studio Native roda de duas formas com o mesmo código:

- **Electron** (o `.exe` do release): janela nativa, backend numa porta sorteada.
- **Navegador**: o próprio Flask serve o front, e você abre no Chrome — ou, com
  um túnel, no celular.

O segundo modo existe para uma coisa concreta: terminar a publicação onde ela
termina de verdade, que é no telefone.

## Rodar

```bash
cd desktop && npm run build     # gera desktop/dist (uma vez, ou após mexer na UI)
python app.py                   # sobe em http://127.0.0.1:5050
```

Abra `http://127.0.0.1:5050`. É o mesmo app, sem Electron.

A porta vem de `STUDIO_PORT` (ou `PORT`), e o host de `STUDIO_HOST`.

## Expor pelo celular com Cloudflare Tunnel

```bash
cloudflared tunnel --url http://127.0.0.1:5050
```

Ele imprime uma URL `*.trycloudflare.com`. Abra no celular.

Para um endereço fixo, use um túnel nomeado apontando para um subdomínio de
`toffa.com.br` — a zona já está na conta.

## ⚠️ Antes de expor: o backend não tem autenticação

Isso nunca foi problema porque ele só escutava em `127.0.0.1`. Atrás de um
túnel, **quem tiver a URL tem o app inteiro**:

- gerar vídeos, gastando seus créditos de OpenRouter e ElevenLabs;
- publicar na sua conta do TikTok;
- ler e alterar as configurações.

**A proteção certa fica no túnel, não no código.** Use **Cloudflare Access**
(Zero Trust → Access → Applications): aponte para o hostname do túnel e exija
login por e-mail — só o seu. O visitante autentica na Cloudflare antes de a
requisição chegar aqui, e o app não precisa saber que isso existe.

Autenticação dentro do app seria pior: mais código para manter, mais um segredo
para guardar, e ainda deixaria o serviço exposto à internet aberta.

Enquanto não houver Access configurado, trate a URL do túnel como uma senha e
derrube o túnel quando terminar.

## O que muda na interface no celular

Abaixo de 720px a barra lateral vira barra fixa no pé, com os destinos
principais. Somem a marca, o histórico e o botão de atualização — atualizar o
instalador é tarefa de quem está no PC.

## A página da legenda

`/?legenda=<id do vídeo>` abre só a legenda, com um botão de copiar. É o destino
do QR code que aparece depois de enviar um vídeo ao TikTok.

Antes o QR carregava o texto dentro dele: a câmera exibia a legenda como texto
solto, e copiar exigia segurar o dedo e ajustar a seleção — justamente com o
TikTok aberto na outra mão.

O QR só aponta para a página quando o app está sendo servido por HTTP; no
Electron (`file://`) não há origem que o telefone possa abrir, e ele volta a
carregar o texto.

**Uma limitação de plataforma:** `navigator.clipboard` só existe em contexto
seguro. Por HTTPS (o caso do túnel) funciona; por HTTP puro num IP da rede
local, não. A página detecta e manda selecionar o texto à mão.

## Por que `/?legenda=` e não `/legenda/`

O build usa `base: "./"` — caminhos relativos, exigência do Electron, que carrega
o `index.html` de `file://`. Numa rota aninhada, o navegador procuraria os assets
em `/legenda/assets/...`, que não existe. Com query string o app vive numa rota
só e os dois modos usam o mesmo build.
