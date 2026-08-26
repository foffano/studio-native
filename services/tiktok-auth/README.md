# Serviço de troca de tokens do TikTok

Cloudflare Worker mínimo. Existe por um motivo só: o `client_secret` do TikTok
**não pode viajar dentro do `.exe`** do Studio Native — qualquer pessoa abre o
pacote do Electron e lê. Este Worker guarda o segredo e faz a troca do `code`
por token em nome do app.

## O que ele não faz — e por que isso é o ponto

- **Não recebe nenhum vídeo.** O MP4 vai direto do computador do usuário para o
  TikTok. É isso que mantém o serviço no plano gratuito para sempre:
  armazenamento e tráfego de vídeo é que custariam caro.
- **Não armazena tokens.** Repassa a resposta do TikTok e esquece.
- **Não registra corpo de requisição nem token em log.**

Volume esperado: ~2 requisições por conta por dia (um login mais uma renovação
de token). O plano gratuito da Cloudflare dá 100 mil por dia.

## Rotas

| Método | Rota | Corpo | Devolve |
| --- | --- | --- | --- |
| `POST` | `/tiktok/token` | `{ code, code_verifier, redirect_uri }` | tokens do TikTok |
| `POST` | `/tiktok/refresh` | `{ refresh_token }` | tokens renovados |
| `GET` | `/tiktok/callback` | — | redireciona o `code` ao loopback do app *(fallback, veja abaixo)* |
| `GET` | `/health` | — | `{ ok: true }` |

O status do TikTok é repassado como está, para o app distinguir erro da
plataforma de erro nosso.

### Proteções

O `redirect_uri` é conferido contra uma **allowlist** no código
(`ALLOWED_REDIRECTS`). O TikTok já valida o redirect contra o que está
registrado no portal; isto é a segunda tranca, para o Worker não poder virar
peça de um fluxo de terceiros. Não há CORS permissivo de propósito: quem chama é
o app desktop, não um navegador.

## Deploy

Pré-requisito: a zona `toffa.com.br` na sua conta Cloudflare. A rota está
declarada como `custom_domain = true` — é isso que faz o wrangler criar o
registro DNS de `auth.` sozinho no deploy. Uma rota comum exigiria que o DNS já
existisse, e sem ele o hostname simplesmente não resolve, mesmo com o Worker
publicado. Nada disso encosta no apex, que já está em uso (inclusive pelo
e-mail no iCloud).

```bash
cd services/tiktok-auth
npm install

# 1) guarde as credenciais do portal do TikTok como secrets
#    (elas NUNCA entram no wrangler.toml nem no git)
npx wrangler secret put TIKTOK_CLIENT_KEY
npx wrangler secret put TIKTOK_CLIENT_SECRET

# 2) publique (a rota auth.toffa.com.br já está no wrangler.toml)
npx wrangler deploy
```

Conferir:

```bash
curl https://auth.toffa.com.br/health
# {"ok":true,"service":"studio-native-tiktok-auth"}
```

Logs ao vivo, sem corpo de requisição: `npx wrangler tail`.

## Sobre o `/tiktok/callback`

Essa rota é **fallback**. Para a plataforma Desktop, o TikTok documenta que o
redirect URI *"must be absolute and begin with https or http"* e *"must be
static"* — ou seja, `http://127.0.0.1:43117/api/tiktok/callback` tende a ser
aceito direto, e aí nenhuma página-ponte é necessária.

Se o portal recusar o loopback, registre
`https://auth.toffa.com.br/tiktok/callback` como redirect URI: essa rota
devolve o usuário ao app pela porta fixa 43117. O `code` passa pelo navegador do
próprio usuário e nunca é armazenado pelo Worker.

A porta 43117 aparece em dois lugares — `LOOPBACK_PORT` aqui e a porta fixa que
o backend do app escuta. Se mudar uma, mude a outra.

## Verificação de domínio no TikTok

Antes de submeter o app para revisão, o TikTok exige verificar as URLs da
configuração. Com o domínio na Cloudflare, use o método de **DNS**: adicione o
registro `TXT` que o portal fornecer em DNS → Records, e verifique. É mais
rápido que o método de arquivo e não depende de nenhuma página estar publicada.
