# Cadastro do app no TikTok for Developers — o que preencher

Textos prontos para colar, com os limites de caracteres já conferidos.

> As URLs abaixo usam `studio.toffa.com.br` (páginas) e `auth.toffa.com.br`
> (serviço de token) — subdomínios novos, que não encostam no apex
> `toffa.com.br`, já em uso. Ter o domínio na Cloudflare resolve a verificação
> por registro TXT no DNS e elimina a única incerteza que restava no cadastro.

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
https://studio.toffa.com.br/termos.html
```

**Privacy Policy URL**

```
https://studio.toffa.com.br/privacidade.html
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

## Verificação das URLs

Antes da submissão, o TikTok exige verificar **todas as URLs da configuração**
(Termos, Privacidade e redirect). Há dois métodos: arquivo na raiz do domínio ou
registro TXT no DNS.

**Com o domínio na Cloudflare, use o DNS.** No portal do TikTok, escolha o
método de verificação por DNS, copie o valor `TXT` que ele fornecer e adicione em
**Cloudflare → seu domínio → DNS → Records → Add record** (tipo `TXT`). Depois
volte ao portal e clique em verificar. É mais rápido que o método de arquivo e
não depende de nenhuma página estar publicada.

Isso encerra a dúvida que existia enquanto a ideia era usar `github.io`: lá a
raiz do domínio pertencia a outro repositório e não havia como criar registros
DNS. Com domínio próprio, não há truque nenhum.

## Publicar as páginas — já está feito

As três páginas estão no ar, servidas como assets estáticos da Cloudflare a
partir de `services/studio-site/public/`:

- `https://studio.toffa.com.br/` — página do app
- `https://studio.toffa.com.br/privacidade.html`
- `https://studio.toffa.com.br/termos.html`

Para republicar depois de editar o HTML: `cd services/studio-site && npx wrangler deploy`.

**Por que não Cloudflare Pages, como estava planejado aqui antes:** Pages pediria
conectar o repositório e adicionar o domínio pelo painel. Com assets estáticos de
Worker o `wrangler deploy` faz tudo por linha de comando, DNS incluído. Mesmo
plano gratuito, mesmo CDN.

**E por que as páginas saíram de `docs/`:** apontar o site para `docs/` publicaria
junto o plano de produto e este próprio formulário. Só entra em `public/` o que é
para ser lido por qualquer um.

### O e-mail de contato

As duas páginas exibem `contato@toffa.com.br`. **Esse endereço ainda precisa
existir de verdade** — a política de privacidade promete um canal de contato, e
o TikTok pode escrever para ele durante a revisão.

Crie no **iCloud**, não na Cloudflare: o domínio já usa iCloud Mail (os MX
apontam para `mx01/mx02.mail.icloud.com`). Ativar o Email Routing da Cloudflare
substituiria esses MX e derrubaria o e-mail que já funciona.

Caminho: iCloud.com → Mail → Configurações → Domínios personalizados →
`toffa.com.br` → adicionar endereço de e-mail. Está incluído no iCloud+.

---

## Redirect URI

Registre, para a plataforma Desktop:

```
http://127.0.0.1:43117/api/tiktok/callback
```

A porta **43117 é fixa** — o TikTok exige URI estático, e hoje o Electron sorteia
uma porta livre. A fase 4 vai reservar essa porta só para o callback.

Se o portal recusar o loopback, o fallback já está pronto: registre
`https://auth.toffa.com.br/tiktok/callback`, que é uma rota do Worker em
`services/tiktok-auth/` e devolve o usuário ao app.

O mesmo Worker guarda o `client_secret` e faz a troca do `code` por token —
o segredo não pode ficar dentro do `.exe`. Deploy e detalhes em
[`services/tiktok-auth/README.md`](../../services/tiktok-auth/README.md).
