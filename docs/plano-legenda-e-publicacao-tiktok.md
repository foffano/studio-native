# Studio Native — de gerador de vídeo a operação de canal

Estudo técnico: o que existe hoje no código, as lacunas que impedem publicar, e um
roteiro de 7 fases para chegar em legenda automática com hashtags, contagem de
produzidos/publicados e publicação no TikTok (inclusive o carrinho laranja).

## 1. O app hoje

Electron abre a janela, o React fala HTTP com o backend Flask (sidecar PyInstaller),
e o Flask renderiza localmente com MoviePy + Pillow + ffmpeg.

Caminho de um vídeo: upload (ou item da Biblioteca) -> `normalize_video()` ->
OpenRouter devolve N frases (`generate_phrases`, app.py:789) -> `render_video()` por
frase -> MP4 em `%APPDATA%/StudioNative/outputs/` -> card com botão Baixar.

Onde o estado mora hoje:

| Onde | O que guarda | Problema |
| --- | --- | --- |
| `library.json` | Vídeos-fonte: status, tags, `generation_count`, `total_outputs` | Conta a fonte, nunca o vídeo gerado |
| `localStorage` do React | Histórico completo, incluindo os arquivos produzidos | O backend não sabe o que ele mesmo produziu |
| `JOBS` (RAM) | Progresso do job | Some no restart; `/api/status` devolve 404 |
| `outputs/` | Os MP4 finais | Sem catálogo e sem limpeza |

Já pronto e reaproveitável: a fila da Biblioteca (worker em thread, recuperação no
startup, tags) e `library_metrics()` (app.py:280) — o catálogo de produção e a fila
de publicação seguem o mesmo padrão.

## 2. As quatro lacunas

1. **Não existe "vídeo produzido" no backend** (bloqueante). Sem essa entidade não
   há como contar publicados, guardar legenda nem publicar.
2. **A IA só devolve a frase de overlay.** O contrato é `{"frases": [...]}`; não há
   legenda nem hashtag em lugar nenhum.
3. **As métricas medem a fonte, não a produção nem a publicação.**
4. **Nenhuma camada de plataforma:** sem contas, OAuth, fila de publicação ou destino.

## 3. O carrinho laranja: dois ecossistemas diferentes

- **Content Posting API** (developers.tiktok.com) publica o vídeo. **Não tem campo
  de produto.**
- **TikTok Shop / Affiliate** (partner.tiktokshop.com) é onde vive o anchor de
  produto. Cadastro separado, aprovação de parceiro (TAP), disponível por região.

Caminhos para o carrinho:

| Caminho | Como funciona | Aprovação | Veredito |
| --- | --- | --- | --- |
| A. Publicar direto, vincular depois no app | Criador adiciona o produto no vídeo já publicado | Audit do Content Posting API | Não |
| B. Enviar como rascunho (`video.upload`) | App manda MP4 + legenda ao inbox; criador adiciona produto e publica | Escopo `video.upload` | **MVP** |
| C. Affiliate Creator API | Anchor programático (único caminho automático) | TAP + aprovação | Fase 6 |
| D. Seller Center depois | Janela de 30 dias, só Commercial Music Library | Nenhuma | Fallback |
| E. Video Shopping Ads | Anchor pago | Conta de anúncios | Fora de escopo |

Limites que precisam aparecer na UI:

- Client não auditado publica **SELF_ONLY**, máximo 5 usuários por 24h.
- O audit reprova por UI fora das Content Sharing Guidelines (ver fase 5).
- TikTok Shop: 7 vídeos shoppable a cada 7 dias; do 8º em diante sai sem produto.

**OAuth em desktop:** o `redirect_uri` da TikTok precisa ser HTTPS em domínio
verificado (não aceita `127.0.0.1` direto) e o `client_secret` não pode viajar dentro
do `.exe`. Duas saídas: um micro-serviço HTTPS próprio (recomendado — também habilita
agendamento com o app fechado) ou só desktop com PKCE, aceitando as limitações.

## 4. Roteiro em sete fases

Estimativas de desenvolvimento, sem contar aprovação da TikTok.

### Fase 1 — Catálogo de produção no backend (2–3 dias, bloqueante)

Cada MP4 renderizado vira registro persistente. `process_job()` grava um registro por
vídeo, no mesmo ponto em que hoje só faz `results.append()`.

Usar **SQLite**, não JSON: três workers vão escrever ao mesmo tempo. Migrar o
localStorage via `POST /api/outputs/import` — conserta de brinde o job perdido no
restart. Incluir política de retenção (limpar saídas acima de X dias / Y GB).

Entregável: `GET /api/outputs` com filtros, `GET/PATCH/DELETE /api/outputs/<id>`,
`GET /api/metrics`.

### Fase 2 — Camada de legenda com hashtags (~2 dias)

Novo contrato com a OpenRouter, tudo numa chamada só:

```json
{"itens": [{"overlay": "frase da tela",
            "caption": "legenda curta do post",
            "hashtags": ["fyp", "receita", "airfryer"]}]}
```

Vale para `generate_phrases()` (app.py:789) e `generate_overlay_and_speech()`
(app.py:927).

**Não confiar na contagem da IA:** `normalize_hashtags()` no backend tira o `#`,
remove espaços/acentos, força minúsculas, deduplica, limita cada tag a ~24 chars e
**corta em 5**. Legenda pedida em até 150 caracteres. Fallback: derivar hashtags do
tema digitado e das tags do item da Biblioteca.

Entregável: legenda editável no card, chips de hashtag, contador 5/5, botão
"gerar outra" (`POST /api/outputs/<id>/caption/regenerate`).

### Fase 3 — Números de produzidos e publicados (~1 dia)

`GET /api/metrics` agrega produzidos, publicados, na fila, com erro, 7/30 dias.
`library_metrics()` ganha `published_count` por fonte — cada card mostra
"12 vídeos · 5 publicados".

### Fase 4 — Conectar a conta do TikTok ✅ feita

Login Kit v2 com PKCE. `tiktok.py` no backend, `TikTokAccount.jsx` na tela de
Ajustes, tokens cifrados com DPAPI (`secretbox.py`) e renovação automática com
30 min de folga antes do vencimento.

Quatro coisas saíram diferentes do que estava escrito aqui, e o motivo importa:

**A porta 43117 não é a do backend.** Fixar o backend inteiro nela faria o app
não abrir quando qualquer outro programa estivesse usando a porta — um modo de
falha permanente para resolver um problema de trinta segundos. Em vez disso,
`tiktok.py` sobe um listener descartável em 43117 só durante o login. O backend
continua na porta sorteada pelo Electron.

**Escopos: só `user.info.basic` e `video.upload`.** O `video.publish` que estava
listado aqui é publicação direta no perfil — não é o caminho escolhido (o
rascunho é o que permite adicionar o carrinho depois) e puxa a revisão mais
rígida do TikTok. Pedir escopo que não se demonstra no vídeo atrasa a revisão.

**O `client_key` vem do Worker, não do `.exe`.** `GET /tiktok/client-key`. Ele é
público, mas embutido no executável a rotação exigiria liberar versão nova para
todos os usuários.

**Não há página-ponte.** O portal aceitou o redirect em loopback direto, então a
rota `/tiktok/callback` do Worker continua existindo só como fallback.

Cifragem: DPAPI do Windows via ctypes, sem dependência nova. `cryptography`
traria binário para o PyInstaller e a chave acabaria guardada ao lado do texto
cifrado — o que é ofuscação, não cifra. Fora do Windows o fallback é ofuscação
declarada, e a UI avisa isso ao usuário em vez de prometer proteção que não tem.

### Fase 5 — Publicar (4–5 dias)

1. `creator_info/query` — obrigatório antes de mostrar a tela (nickname, opções de
   privacidade, duração máxima, se comentário/duet/stitch estão desativados).
2. `video/init` com `source=FILE_UPLOAD`.
3. `PUT` dos chunks.
4. `publish/status/fetch` em polling — mesmo padrão do `generationManager.js`.

Fila com worker único, retry com backoff e respeito ao rate limit — estrutura igual
à fila da Biblioteca (app.py:366).

Obrigatório na tela (é onde o audit reprova):

- Nickname da conta de destino visível.
- Privacidade em dropdown **sem valor pré-selecionado**, com as opções do `creator_info`.
- Toggles de comentário/duet/stitch espelhando o `creator_info`.
- Declaração de conteúdo comercial com o texto de consentimento da TikTok.
- Estado explícito de "publicando" e confirmação.

Agendamento: a API não agenda. Ou scheduler local (app aberto) ou o micro-serviço —
e a UI precisa dizer qual dos dois é.

### Fase 6 — O produto no vídeo (1 dia MVP / 5+ dias Shop)

MVP: ao marcar "tem produto", publicar como **rascunho** com legenda e hashtags
preenchidas + checklist de dois passos. O registro guarda a intenção de produto.
Depois: Affiliate Creator API atrás de flag, com catálogo em cache. Prever
`product_ids` e `product_mode` no modelo desde a fase 1.

### Fase 7 — Reforma da navegação (3–4 dias)

Pode andar em paralelo a partir da fase 3.

## 5. Modelo de dados

```
# outputs — um registro por MP4 renderizado
id, job_id, library_id, file, phrase, speech,
caption (fase 2), hashtags json (fase 2, máx 5 sanitizadas),
duration, created_at,
status            # rascunho | pronto | publicado | arquivado

# publications — uma linha por tentativa de publicação
id, output_id, platform, account_id, publish_id,
mode              # direct_post | draft
privacy           # escolhido pelo usuário, sem default
product_mode      # nenhum | manual_no_app | shop_api
product_ids json,
state             # fila | enviando | processando | publicado | erro
error, scheduled_for, published_at, post_url

# accounts — contas conectadas
id, platform, open_id, nickname, avatar_url,
access_token_enc, refresh_token_enc, expires_at,
scopes, audited, created_at
```

Métricas: **produzidos** = `count(outputs)`; **publicados** =
`count(distinct output_id)` em `publications` com `state='publicado'` — distinto de
propósito, para um vídeo postado em duas contas não contar dobrado.

## 6. UX / UI

A unidade de trabalho deixa de ser *a geração* (barra lateral estilo chat) e passa a
ser *o vídeo produzido*: ele nasce, ganha legenda, entra na fila, é publicado.

Nova navegação:

1. **Painel** (novo) — KPIs, agendados de hoje, últimos publicados.
2. **Gerar** (como hoje) — com passo de legenda no fim.
3. **Fontes** (renomear "Biblioteca") — vídeos crus.
4. **Produzidos** (novo) — grade dos MP4, filtro por estado, seleção múltipla.
5. **Publicações** (novo) — fila, agendados, histórico com link e erro.
6. **Ajustes** — ganha a aba Contas.

Sete mudanças pontuais com retorno alto:

1. Card de resultado ganha legenda editável, chips de hashtag e ação **Publicar** ao
   lado de Baixar (hoje só há Baixar — GenerateView.jsx:689).
2. `STAGES` ganha "Legenda" entre "Frases" e "Renderizar"; publicação com barra
   própria (Enviando -> TikTok processando -> Publicado).
3. Ações em lote em Produzidos: enfileirar 5 vídeos com intervalo.
4. Selo fixo de "modo sandbox" enquanto o client não for auditado.
5. Contador "5 de 7 nesta semana" ao lado do seletor de produto.
6. Estado vazio de Publicações ensina a conectar a conta.
7. Histórico vindo do backend elimina o bug de geração eternamente "rodando".

Decisão de produto: com "Produzidos" existindo, a barra lateral deveria virar só
navegação + o que está em andamento, e o acervo morar inteiro em Produzidos.

## 7. Decisões que dependem de você

1. **SQLite ou JSON?** Recomendo SQLite — vem no Python e aguenta os três workers.
2. **Vai existir micro-serviço HTTPS?** Recomendo que sim — resolve `redirect_uri`,
   `client_secret` e agendamento com o app fechado.
3. **Carrinho: rascunho agora ou esperar a TikTok Shop?** Recomendo rascunho agora.
4. **Você já tem conta TikTok Shop / é afiliado aprovado?** Define se a fase 6
   completa é viável. Se não, começar o cadastro em paralelo à fase 1.
5. **Só TikTok ou já abrir para Reels/Shorts?** Recomendo abrir — o campo `platform`
   custa nada agora.

**Por onde começar:** fases 1 e 2 juntas, em uma semana — não dependem de aprovação
de ninguém e deixam a fundação pronta. Em paralelo, abrir o cadastro do app no
TikTok for Developers, porque a espera corre sozinha.

## 8. Fontes

O domínio `developers.tiktok.com` estava bloqueado no ambiente desta análise; os
detalhes da API foram confirmados por fontes secundárias. **Conferir os nomes exatos
dos campos na documentação oficial antes de implementar a fase 5.**

- https://developers.tiktok.com/products/content-posting-api/
- https://developers.tiktok.com/docs/en/content-sharing-guidelines
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- https://partner.tiktokshop.com/docv2/page/affiliate-creator-api-overview
- https://partner.tiktokshop.com/docv2/page/add-showcase-products-202405
- https://seller-us.tiktok.com/university/essay?knowledge_id=5178002307598122&lang=en
- https://www.bigseller.com/blog/articleDetails/4203/tiktok-shop-content-posting-limit.htm
- https://bundle.social/blog/tiktok-api-approval
