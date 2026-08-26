# Cadastro do app no TikTok for Developers — o que preencher

Textos prontos para colar, com os limites de caracteres já conferidos.
Substitua `foffano.github.io/studio-native` se você publicar as páginas em outro
endereço.

---

## Basic information

**App icon** — use `docs/tiktok/app-icon-1024.png` (1024×1024, PNG, 0,52 MB).
Gerado a partir do logo do projeto e achatado sobre branco, porque transparência
vira preto em várias previews do portal.

**App name**

```
Studio Native
```

**Category** — `Productivity`.

**Description** (limite 120; o texto abaixo tem 106)

```
Gera videos curtos verticais com apoio de IA no seu computador e os envia para os rascunhos do seu TikTok.
```

> Em inglês, se preferir (90 caracteres):
> `Create short vertical videos with AI on your computer and send them to your TikTok drafts.`

**Terms of Service URL**

```
https://foffano.github.io/studio-native/termos.html
```

**Privacy Policy URL**

```
https://foffano.github.io/studio-native/privacidade.html
```

**Platforms** — marque **apenas `Desktop`**.

Isso importa mais do que parece: para a plataforma Desktop o TikTok documenta que
o redirect URI *"must be absolute and begin with https or http"* e *"must be
static"*. Ou seja, `http://127.0.0.1:43117/callback` tende a ser aceito, e aí você
não precisa hospedar página-ponte nenhuma. A exigência é que a **porta seja fixa**
— o Electron hoje sorteia uma porta livre, então a fase 4 precisa reservar uma
porta fixa só para o callback.

Marcar `Web` sem ter site de verdade só cria exigências extras na revisão.

---

## Products e Scopes

Adicione **apenas** o que você vai demonstrar no vídeo. O próprio formulário
avisa: escopo pedido e não demonstrado **atrasa a revisão**.

| Produto | Escopo | Por quê |
| --- | --- | --- |
| Login Kit | `user.info.basic` | Mostrar apelido e avatar da conta conectada, para o usuário confirmar o destino |
| Content Posting API | `video.upload` | Enviar o vídeo para os **rascunhos** da conta do usuário |

**Não peça `video.publish` agora.** Ele é a publicação direta no perfil — não é o
caminho que escolhemos (o rascunho é o que permite adicionar o produto/carrinho
laranja no app do TikTok) e é o escopo que puxa a revisão mais rígida. Se um dia
você quiser postar direto, sem abrir o celular, é só pedir numa revisão posterior.

---

## App review

**"Explain how each product and scope works within your app"** (limite 1000; o
texto abaixo tem 999)

```
Studio Native is a Windows desktop app that helps a creator produce short vertical videos. The user picks their own video, the app overlays AI-generated text locally with ffmpeg and writes a post caption with up to 5 hashtags. No video is sent to any third party during generation.

Login Kit (user.info.basic): in Settings the user clicks "Connect TikTok". We open the system browser to TikTok's authorization page. We use user.info.basic only to show the connected account's nickname and avatar in the app, so the user can confirm which account they are sending to.

Content Posting API (video.upload): on a generated video the user clicks "Send to TikTok". We call creator_info/query to display the creator's nickname and settings, then upload the file directly from the user's computer to their TikTok DRAFTS. The user then opens TikTok to review, optionally add a product link, and publish.

We never post publicly on the user's behalf: publishing is always completed by the user inside TikTok.
```

> Escreva em inglês. Os revisores não são de língua portuguesa, e um texto que
> eles não conseguem ler é rejeição garantida — com semanas de custo.

### Vídeo de demonstração

Este é o item que **ainda não dá para entregar**: ele exige as fases 4 e 5
construídas. O que a gravação precisa mostrar, na ordem:

1. O aplicativo **sendo aberto** (é exigência explícita para apps instalados).
2. Ajustes › Contas → "Conectar TikTok" → navegador abrindo a tela de
   autorização → voltando para o app já conectado, **com o apelido e o avatar
   visíveis** (é a prova de uso do `user.info.basic`).
3. Um vídeo gerado → "Enviar para o TikTok" → a tela mostrando o apelido do
   criador vindo do `creator_info` → o envio → confirmação de sucesso.
4. O TikTok aberto mostrando o vídeo **nos rascunhos** — é o que fecha a
   demonstração do `video.upload`.

Regras que costumam reprovar a submissão: use o **ambiente de sandbox** do portal
(obrigatório para app nunca aprovado); demonstre **todos** os escopos pedidos e
remova os que não usar; mostre claramente a interface e os cliques. Limite de 5
arquivos, 50 MB cada, mp4 ou mov.

---

## Sequência recomendada

Criar o app **não** é o mesmo que submeter à revisão. Vale separar:

1. **Agora:** preencha o Basic information, marque `Desktop`, adicione os dois
   escopos e salve. Isso já libera o `client_key` e o `client_secret`, e o
   desenvolvimento da fase 4 pode começar.
2. **Antes de submeter:** verifique as URLs (abaixo) e grave o vídeo de
   demonstração com as fases 4 e 5 prontas.
3. **Depois:** submeta para revisão.

---

## Verificação das URLs — o detalhe que trava

Antes da submissão, o TikTok exige verificar **todas as URLs da configuração**
(Termos, Privacidade e redirect), por arquivo na raiz do domínio
(`tiktok-developers-site-verification.txt`) ou por registro TXT no DNS.

Com GitHub Pages de repositório, suas páginas ficam em
`foffano.github.io/studio-native/...`, mas a **raiz** do domínio é
`foffano.github.io` — que pertence a outro repositório. Se o TikTok pedir o
arquivo na raiz, crie um repositório público chamado exatamente
**`foffano.github.io`** (grátis) e coloque o arquivo de verificação na raiz dele.

Não dá para garantir que o TikTok aceite subdomínios de hospedagem compartilhada
como `github.io`. Se ele recusar, aí sim vale um domínio próprio (~R$50/ano),
que resolve verificação e página-ponte de uma vez.

---

## Publicar as páginas (2 cliques, grátis)

As páginas já estão no repositório, em `docs/`. Para ficarem no ar:

**Settings → Pages → Source: `Deploy from a branch` → Branch: `main`, pasta
`/docs` → Save.**

Em um ou dois minutos:

- `https://foffano.github.io/studio-native/` — página do app
- `https://foffano.github.io/studio-native/privacidade.html`
- `https://foffano.github.io/studio-native/termos.html`

**Antes de publicar:** as duas páginas têm um campo
`[preencha com o e-mail de contato]`. Troque pelo e-mail que você quer expor
publicamente — considere criar um endereço só para isso, em vez de usar o
pessoal. E leia os dois textos: eles descrevem o comportamento real do app, mas
quem responde por eles é você.
