# De aplicativo instalado a serviço web

Análise para a mudança pedida: tirar o Electron, deixar o app rodando só no
navegador, protegido por senha, como serviço em segundo plano no PC, exposto em
`native.toffa.com.br`.

Resposta curta: **é viável e o código já está 70% do caminho**, mas há três
pontos que mudam de natureza — não de tamanho — e um deles pode travar o TikTok
no celular. Este documento existe para essas três decisões serem tomadas antes
de qualquer linha ser escrita.

---

## 1. O que já está pronto

O modo navegador foi construído na 1.2.0 e funciona: o Flask serve o front em
`/`, o React usa a mesma origem, e o layout se adapta a telas de celular.
Rodando `python app.py`, o app inteiro está no navegador hoje.

O trabalho restante **não é portar o app**. É o que vem depois disso:
autenticação, servidor de produção, serviço em segundo plano, e a distribuição.

## 2. Superfície de ataque, hoje

| | Situação |
| --- | --- |
| Rotas expostas | **34** |
| Rotas com autenticação | **0** |
| `Access-Control-Allow-Origin` | `*` |
| Servidor | `app.run()` — servidor de desenvolvimento do Flask |

Duas dessas rotas merecem destaque porque não parecem perigosas e são:

```
GET /outputs/<filename>    -> serve qualquer MP4 produzido
GET /library/<filename>    -> serve qualquer vídeo-fonte
```

Sem autenticação, quem souber (ou adivinhar) um nome de arquivo baixa o vídeo.
Proteger só a "tela de admin" e deixar estas duas abertas seria proteger a porta
e deixar a janela escancarada.

O CORS aberto tem um comentário no código explicando o porquê: *"o servidor só
escuta em 127.0.0.1"*. Essa premissa deixa de valer no momento em que o túnel
sobe, e o comentário vira uma justificativa obsoleta para um buraco.

**`app.run()` não é servidor de produção.** A própria documentação do Flask diz
isso. Exposto à internet, ele é single-threaded por requisição pesada, não tem
limites de conexão e não foi auditado para essa finalidade. Precisa de
[waitress](https://pypi.org/project/waitress/) — Python puro, funciona no
Windows, empacota no PyInstaller sem drama. É a única dependência nova.

## 3. As três decisões que precisam ser tomadas

### 3.1 O OAuth do TikTok quebra no celular

Este é o ponto mais delicado, e não é óbvio.

O login do TikTok redireciona para `http://127.0.0.1:43117/api/tiktok/callback`.
Do navegador **no mesmo PC**, funciona. **Do celular, não**: `127.0.0.1` no
telefone é o próprio telefone, que não tem servidor nenhum escutando ali.

Saídas possíveis:

1. **Usar o fallback do Worker.** A rota `/tiktok/callback` já existe em
   `services/tiktok-auth/`, mas hoje redireciona para o loopback. Passaria a
   redirecionar para `https://native.toffa.com.br/api/tiktok/callback`, e o
   backend receberia o `code` por lá. Exige registrar esse redirect URI no
   portal do TikTok — o app está em sandbox, então dá para mudar sem revisão.
2. **Conectar a conta só pelo PC.** O login continua pelo loopback; do celular
   você usa tudo, menos conectar/reconectar a conta. Custo zero de código.

A opção 1 é a certa se o objetivo é operar do celular de verdade. A 2 é honesta
se conectar a conta é algo que acontece uma vez por ano.

### 3.2 A senha e o DPAPI não podem ser a mesma coisa

Tentação natural: derivar a chave de cifragem dos tokens da senha do admin.
Seria mais elegante — a senha protegeria tudo.

**Não funciona com serviço em segundo plano.** O serviço sobe no boot, sem
ninguém para digitar a senha, e precisa decifrar os tokens do TikTok para
renovar a sessão. Com a chave derivada da senha, ele subiria inútil.

Então: **DPAPI continua cifrando os tokens** (amarrado à conta Windows) e a
senha protege o *acesso HTTP*. São camadas diferentes, com finalidades
diferentes. Vale escrever isso no código, porque a próxima pessoa a olhar vai ter
a mesma ideia.

Consequência prática: **o serviço tem que rodar como o usuário `marlo`**, não
como SYSTEM. Rodando como SYSTEM, o DPAPI não decifra e a conta do TikTok
"desconecta" sozinha, sem explicação.

### 3.3 Sem Electron, some o auto-update

Hoje o app instalado se atualiza sozinho a partir das releases do GitHub
(`electron-updater`). Isso é do Electron. Sem ele:

- não há mais instalador de um clique;
- não há mais atualização automática;
- atualizar passa a ser trocar o executável (ou `git pull`) à mão.

Para um app pessoal, aceitável. Vale saber que é uma troca, não um ganho puro.

**O PyInstaller continua valendo a pena**: ele gera um executável do backend que
não exige Python instalado. Some o Electron (350 linhas, ~600 MB de instalador),
fica o `StudioNativeBackend.exe` rodando como serviço.

## 4. Desenho da autenticação

Requisito: seguro de verdade, porque fica exposto à internet num hostname que
aparece nos logs públicos de Certificate Transparency minutos depois de criado.

Tudo com a biblioteca padrão e o que o Flask já traz — sem dependência nova:

| Peça | Como |
| --- | --- |
| Hash da senha | `hashlib.scrypt` (stdlib), com sal aleatório por instalação |
| Sessão | cookie assinado do Flask (`itsdangerous`, já vem junto) |
| Cookie | `HttpOnly`, `Secure`, `SameSite=Lax` |
| Comparação | `hmac.compare_digest`, para não vazar por tempo de resposta |
| Força bruta | atraso progressivo e bloqueio temporário por IP |
| Cobertura | **todas** as 34 rotas, inclusive `/outputs/` e `/library/` |
| Exceções | `/api/health` (para o túnel checar) e os assets do front |

A senha fica em `config.json` como hash scrypt — nunca em texto puro. Primeira
execução sem senha definida: o app exige criar uma antes de liberar qualquer
outra coisa.

**Cloudflare Access continua valendo mesmo com senha própria.** Ele barra o
tráfego antes de chegar ao seu PC; a senha do app é a segunda tranca. As duas
juntas custam pouco e cobrem falhas diferentes: o Access protege contra o mundo,
a senha protege contra um Access mal configurado.

## 5. O que fazer, em ordem

Cada fase é útil sozinha — dá para parar em qualquer uma.

**Fase A — Autenticação (~1 dia).** Login, sessão, proteção de todas as rotas,
CORS restrito à própria origem. Sem isto, nada mais deve ir para a internet.

**Fase B — Servidor de produção (~2 horas).** Trocar `app.run()` por waitress.
Acrescenta uma dependência e some com o aviso de "development server".

**Fase C — Serviço em segundo plano (~meio dia).** Tarefa agendada rodando
`StudioNativeBackend.exe` como `marlo`. Gatilho "ao fazer logon" não pede senha
do Windows; "ao iniciar o sistema" pede, e é a única forma de rodar com o PC
bloqueado.

**Fase D — Túnel e domínio (~1 hora).** Rota `native.toffa.com.br` no
`fazenda.yml`, registro DNS via `cloudflared tunnel route dns`, reinício do
serviço. **Depois do Access configurado**, não antes.

**Fase E — Aposentar o Electron (~meio dia).** Remover `desktop/electron/`, o
`electron-builder`, o `electron-updater` e a ponte do preload. O `api.js` perde
o caminho da ponte e fica só com a mesma origem. Atalho no menu Iniciar abrindo
o navegador no endereço.

**Fase F — OAuth pelo celular (~meio dia).** Só se a decisão 3.1 for pela opção
1: mudar o Worker, registrar o novo redirect URI no portal do TikTok, ajustar
`tiktok.py`.

## 6. O que muda para você, na prática

| | Hoje | Depois |
| --- | --- | --- |
| Abrir o app | ícone no Windows | atalho que abre o navegador |
| De outro dispositivo | não dá | `native.toffa.com.br`, com senha |
| Atualizar | automático | manual |
| Instalar em outro PC | um instalador de 600 MB | copiar a pasta e criar a tarefa |
| Se o PC estiver desligado | app não abre | site fora do ar |
| Superfície exposta | nenhuma | uma porta na internet, com senha |

A última linha é a que importa. Hoje o app é inalcançável de fora — não por
esforço de segurança, mas por não estar em lugar nenhum. Depois, ele passa a
estar, e a segurança deixa de ser uma consequência do isolamento e passa a ser
uma coisa que o código precisa fazer certo.
