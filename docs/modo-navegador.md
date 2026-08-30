# Modo navegador e acesso pelo celular

O Studio Native roda de duas formas com o mesmo código:

- **Electron** (o `.exe` do release): janela nativa, backend numa porta sorteada.
- **Navegador**: o próprio Flask serve o front, e você abre no Chrome — ou, com
  um túnel, no celular.

O segundo modo existe para uma coisa concreta: terminar a publicação onde ela
termina de verdade, que é no telefone.

## Rodar

### Se você usa o app instalado

Basta deixá-lo aberto: o backend dele já serve o navegador. O endereço aparece
em **Ajustes → Abrir no navegador**, com botão de copiar e um QR.

O app tenta a porta **5050** e só sorteia outra se ela estiver ocupada — por
isso o endereço costuma ser sempre `http://127.0.0.1:5050`, mas confira no
cartão em vez de supor. Antes da versão 1.2.2 a porta era sempre sorteada, e não
havia como descobri-la sem um `netstat`.

### Se você roda pelo código-fonte

```bash
cd desktop && npm run build     # gera desktop/dist (uma vez, ou após mexer na UI)
python app.py                   # sobe em http://127.0.0.1:5050
```

A porta vem de `STUDIO_PORT` (ou `PORT`), e o host de `STUDIO_HOST`.

## Rodar em segundo plano

O backend fica de pe sozinho, sem janela nenhuma, como tarefa do Agendador do
Windows:

```powershell
powershell -ExecutionPolicy Bypass -File tools\instalar-servico.ps1
```

Isso cria a tarefa `StudioNative`, com gatilho **ao fazer logon** -- ela sobe
quando voce entra no Windows e continua rodando com tudo fechado.

Para subir junto com o Windows, **antes de voce desbloquear**:

```powershell
powershell -ExecutionPolicy Bypass -File tools\instalar-servico.ps1 -Gatilho AoIniciar
```

O Windows exige guardar a senha da sua conta para isso, e vai pedir numa caixa
propria. Precisa de PowerShell como Administrador.

### Por que como usuario, e nao como SYSTEM

Servico do Windows normalmente roda como SYSTEM. Aqui **nao pode**: os tokens do
TikTok sao cifrados com DPAPI, amarrado a conta `marlo`. Rodando como SYSTEM, a
decifragem falharia e o app pediria para reconectar a conta a cada renovacao de
sessao -- sem dizer o motivo, porque do ponto de vista dele o token
simplesmente nao existe.

Por isso `pythonw.exe` (sem janela de console) rodando como o proprio usuario, e
nao um servico de verdade.

### Por que do repositorio, e nao do executavel empacotado

O `dist/StudioNativeBackend/` e apagado a cada rebuild do PyInstaller. Uma
tarefa apontando para la pararia de funcionar no meio de um build, e o sintoma
seria o site fora do ar sem motivo aparente.

### Comandos

```powershell
Start-ScheduledTask StudioNative
Stop-ScheduledTask  StudioNative
Get-ScheduledTask   StudioNative | Get-ScheduledTaskInfo
Unregister-ScheduledTask StudioNative -Confirm:$false
```

A tarefa reinicia sozinha se o processo cair (ate 999 vezes, a cada minuto) e
nao tem limite de execucao -- o padrao do Windows mata tarefas depois de 3 dias,
e um servico que morre sozinho num sabado e pior que um que nunca subiu, porque
ninguem percebe.

## Endereco publico: native.toffa.com.br

Ja esta no ar. A rota vive no tunel `fazenda`, que roda como servico do Windows
nesta maquina:

- config: `C:\Users\marlo\.cloudflared\fazenda.yml`
- regra: `native.toffa.com.br` -> `http://localhost:5050`
- tunel: `5f458d5a-a65a-4c45-9576-292ec8f71032`

O tunel so entrega enquanto o backend estiver de pe na 5050. Com ele parado, a
Cloudflare devolve 502.

**Reiniciar o servico exige PowerShell como Administrador:**

```powershell
Restart-Service Cloudflared -Force
```

Sem elevacao, o `Restart-Service` reporta "Running" sem ter reiniciado nada -- o
processo antigo continua com a config velha em memoria, e a regra nova nao vale.
O jeito de conferir se pegou e o `CREATED` do conector:

```bash
cloudflared tunnel info fazenda
```

**Uma armadilha na criacao do DNS:** `cloudflared tunnel route dns` cria o
registro na zona do `cert.pem`, nao na zona do hostname que voce pediu. Com um
certificado emitido para outra zona, ele cria algo como
`native.toffa.com.br.outrazona.cfd` e nao avisa que fez besteira. Se acontecer,
refaca o `cloudflared tunnel login` escolhendo a zona certa.

## Expor uma URL temporaria com Cloudflare Tunnel

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
