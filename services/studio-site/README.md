# Páginas públicas do Studio Native

As três páginas que o cadastro do TikTok exige, servidas em
`https://studio.toffa.com.br` como assets estáticos da Cloudflare:

- `/` — página do app
- `/privacidade.html` — Política de Privacidade
- `/termos.html` — Termos de Uso

## Por que não é `docs/`

Porque `docs/` guarda também o plano de produto e o rascunho do formulário de
cadastro — material interno. Apontar o site para `docs/` publicaria os dois.
Aqui em `public/` só entra o que é para ser lido por qualquer um.

## Por que não é Cloudflare Pages

Pages exigiria conectar o repositório e adicionar o domínio pelo painel. Com
assets estáticos de Worker o `wrangler deploy` resolve tudo por linha de
comando, DNS incluído. O plano gratuito e o CDN são os mesmos.

## Deploy

```bash
cd services/studio-site
npm install
npx wrangler deploy
```

Conferir:

```bash
curl -I https://studio.toffa.com.br/termos.html
```
