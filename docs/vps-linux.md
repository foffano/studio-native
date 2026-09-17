# Rodar numa VPS Linux

O Studio Native nasceu para rodar num PC com Windows, mas nada nele exige o
Windows. Este guia leva o app para uma VPS Linux, de pé 24 horas, sem depender
de nenhum computador ligado em casa.

## O desenho

```
Navegador (PC ou celular)
        │  https://native.toffa.com.br
        ▼
Cloudflare (Access, se configurado)
        │
        ▼
cloudflared ── na própria VPS
        │  http://127.0.0.1:5050
        ▼
Flask + waitress (serviço do systemd, usuário `studio`)
        │
        ├── ffmpeg / MoviePy / Pillow ── render local
        ├── /var/lib/studio-native ──── dados
        └── MP4 → TikTok, direto
```

**O app confia nos cabeçalhos da Cloudflare** — o IP real do visitante e o fato
de o pedido ter chegado por HTTPS — **só quando eles vêm de um proxy conhecido.**
Com o cloudflared na mesma máquina, isso é o loopback, e funciona sem
configurar nada. Com o túnel em container, o pedido chega do IP da rede do
Docker, e é preciso declarar essa rede em `STUDIO_TRUSTED_PROXIES`. Sem isso o
freio de força bruta trata o mundo inteiro como um IP só: cinco senhas erradas
de qualquer pessoa trancam a porta para você também.

Este guia descreve a instalação direta na máquina (systemd). Se a sua VPS já
roda apps em Docker atrás de um cloudflared, veja **"Numa VPS que já roda
Docker"**, mais abaixo.

**O endereço continua `native.toffa.com.br`.** Assim o retorno do login do
TikTok, registrado no portal e no `ALLOWED_REDIRECTS` do Worker, não muda, e o
Cloudflare Access continua valendo.

## O que muda em relação ao Windows

| | PC com Windows | VPS |
| --- | --- | --- |
| Mantém o app de pé | Tarefa agendada | `studio-native.service` (systemd) |
| Dados | `%APPDATA%\StudioNative` | `/var/lib/studio-native` |
| Tokens do TikTok | DPAPI | AES-GCM, chave em `/etc/studio-native/token.key` |
| ffmpeg | `bin/`, via `fetch_ffmpeg.py` | pacote do sistema (`apt`) |
| Emojis nas frases | Segoe UI Emoji | Noto Color Emoji |
| Atualizar | `tools\atualizar.ps1` | `tools/atualizar.sh` |
| Backup | nenhum | cópia diária do banco, e dos vídeos com rclone |

Os emojis ficam com o desenho do Google em vez do da Microsoft. O tamanho e a
posição na frase são os mesmos.

## Requisitos

- **Debian 12+ ou Ubuntu 22.04+**, com systemd e acesso root por `sudo`.
- **2 vCPU e 4 GB de RAM** dão conta com um render por vez
  (`STUDIO_RENDER_SLOTS=1`). **4 vCPU e 8 GB** ficam confortáveis. São
  estimativas: meça uma geração real antes de escolher o plano de vez.
- **Disco** para a Biblioteca e os vídeos produzidos, que só crescem. O upload
  recusa um vídeo quando não sobra espaço para ele mais 512 MB.
- O domínio na Cloudflare (o `toffa.com.br` já está).

## 1. Instalar

```bash
sudo git clone https://github.com/foffano/studio-native.git /opt/studio-native
sudo chown -R "$USER": /opt/studio-native
sudo /opt/studio-native/tools/instalar-vps.sh
```

O repositório fica em `/opt`, e não na sua pasta pessoal, porque o serviço roda
como o usuário `studio` e não enxerga pastas pessoais. O instalador recusa
rodar de `/home` ou `/root` por esse motivo.

O instalador:

1. instala Python, ffmpeg, a fonte de emoji e uma fonte de texto de reserva;
2. baixa o Node LTS oficial do nodejs.org, se o do sistema não servir ao Vite 8
   (que exige Node 20.19+ ou 22.12+);
3. cria o usuário de sistema `studio`, dono só dos dados;
4. monta o venv do Python e faz o build do front como o dono do repositório;
5. gera a chave dos tokens e o arquivo de configuração em `/etc/studio-native`;
6. instala e sobe o serviço e o backup diário, e confere se o app responde.

Pode rodar de novo à vontade. É assim que se aplica uma mudança em `deploy/`.
Chave e configuração que já existem nunca são sobrescritas.

## 2. Configurar

A configuração fica em `/etc/studio-native/studio-native.env`:

| Variável | Para que serve |
| --- | --- |
| `STUDIO_PUBLIC_URL` | Endereço público. O TikTok devolve o navegador para `<este endereço>/api/tiktok/callback` depois do login, e isso tem que bater byte a byte com o registrado no portal e no Worker. |
| `STUDIO_HOST`, `STUDIO_PORT` | Onde o app escuta: `127.0.0.1:5050`. Nunca `0.0.0.0`, porque quem fala com a internet é o túnel. |
| `STUDIO_COOKIE_SECURE` | `1`: o cookie de sessão só viaja por HTTPS. Por isso não dá para fazer login por `http://127.0.0.1` num túnel SSH. |
| `STUDIO_DATA_DIR` | Pasta de dados. Se mudar, ajuste `StateDirectory` e `ReadWritePaths` nas unidades em `deploy/`. |
| `STUDIO_TMP_DIR` | Temporários de upload. Ficam no disco porque em algumas distros `/tmp` é memória. |
| `STUDIO_RENDER_SLOTS` | Quantos renders e normalizações rodam ao mesmo tempo. Quem espera vê "Aguardando vaga..." na tela. |
| `STUDIO_TRUSTED_PROXIES` | Redes de onde os cabeçalhos da Cloudflare valem, além do loopback. Só é preciso quando o túnel não roda na própria máquina — por exemplo `172.16.0.0/12` para um cloudflared em container. |

Depois de mudar algo:

```bash
sudo systemctl restart studio-native
```

### A chave dos tokens

`/etc/studio-native/token.key` cifra os tokens do TikTok. O arquivo é só do
root. O systemd entrega ao serviço uma cópia que nenhum outro processo lê
(`LoadCredential`), fora da pasta de dados. Um backup ou snapshot de
`/var/lib/studio-native` sozinho não abre os tokens.

**Guarde uma cópia da chave fora da VPS.** Sem ela, nada se perde além das
sessões: basta reconectar as contas do TikTok.

Se a chave estiver ilegível, o serviço não sobe, de propósito. Cair em silêncio
numa chave local cifraria os tokens novos com a chave errada.

## 3. Túnel da Cloudflare

O jeito mais simples é o túnel gerenciado pelo painel:

1. **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared.** O painel
   mostra os comandos para instalar o `cloudflared` no Debian/Ubuntu e ligá-lo
   com um token. Rode-os na VPS.
2. **Public Hostname:** `native.toffa.com.br` → `HTTP` → `127.0.0.1:5050`.

Use `127.0.0.1`, e não `localhost`. O app escuta só em IPv4, e `localhost` pode
resolver para `::1`, o que dá 502 sem explicação.

**O hostname hoje aponta para o túnel `fazenda`, no Windows.** Antes de criar o
Public Hostname novo:

1. Apague o registro DNS `native` da zona `toffa.com.br`. O painel recusa criar
   um hostname que já tem registro.
2. Tire a regra `native.toffa.com.br` do `C:\Users\marlo\.cloudflared\fazenda.yml`
   e reinicie o serviço do cloudflared no Windows (PowerShell como
   Administrador: `Restart-Service Cloudflared -Force`).

O Access continua valendo sozinho: a aplicação dele é ligada ao hostname, não ao
túnel.

## 4. Trazer os dados do Windows

No Windows, no PowerShell, a partir do repositório:

```powershell
powershell -ExecutionPolicy Bypass -File tools\exportar-para-vps.ps1
```

O script desliga a tarefa agendada, confere que nada mais está servindo na 5050
e gera `studio-dados.tar.gz` na Área de Trabalho. Depois:

```powershell
scp "$HOME\Desktop\studio-dados.tar.gz" usuario@sua-vps:/tmp/studio-dados.tar.gz
```

Na VPS:

```bash
sudo /opt/studio-native/tools/importar-dados.sh /tmp/studio-dados.tar.gz
```

Vêm junto a senha de acesso, as chaves de API, as vozes, a Biblioteca, os
vídeos produzidos e o catálogo. Se já havia dados na VPS, eles são guardados em
`/var/lib/studio-native.antes-da-importacao-<data>`, e nada é apagado.

A tarefa do Windows fica desligada de propósito, para os dois lugares não
responderem ao mesmo tempo. Para voltar ao Windows:
`Enable-ScheduledTask StudioNative; Start-ScheduledTask StudioNative`.

## 5. Reconectar o TikTok

Os tokens vieram cifrados com o DPAPI do Windows, e o DPAPI só abre na mesma
conta do mesmo Windows. As contas aparecem em Ajustes, mas publicar responde
"Os tokens salvos nao podem ser lidos nesta maquina".

Em **Ajustes → Conta do TikTok**, conecte cada conta de novo. Faça isso pelo
endereço público: o retorno do login cai em `STUDIO_PUBLIC_URL`, e é lá que a
sua sessão precisa existir.

## Atualizar

Como o dono do repositório, sem `sudo`:

```bash
/opt/studio-native/tools/atualizar.sh
```

O script puxa o código, atualiza as dependências, constrói o front numa pasta
nova e só então reinicia o serviço. Se qualquer passo falhar, o serviço
continua servindo a versão anterior, com o front anterior. `--sem-git` pula o
`git pull`.

## Backup

Todo dia, às 4h30 (com até 20 minutos de variação), o
`studio-native-backup.timer` faz uma cópia consistente do `studio.db`, do
`config.json` e do `library.json` em `/var/backups/studio-native` e guarda as
últimas 14.

**Isso não protege contra a perda do disco da VPS.** Para isso, mande tudo para
fora com o rclone (R2, B2, S3, Google Drive...):

```bash
sudo apt install rclone
sudo rclone config --config /etc/studio-native/rclone.conf
sudo chown root:studio /etc/studio-native/rclone.conf
sudo chmod 640 /etc/studio-native/rclone.conf
echo 'RCLONE_REMOTE=meuremoto:studio-native' | sudo tee /etc/studio-native/backup.env
sudo systemctl start studio-native-backup   # testa agora
journalctl -u studio-native-backup -n 20
```

Com o remoto, os vídeos (`library/`, `library_thumbs/`, `outputs/`) também vão.
Um vídeo apagado aqui não some do remoto: vai para `apagados/<data>`.

Para restaurar o banco:

```bash
sudo systemctl stop studio-native
sudo -u studio cp /var/backups/studio-native/<data>/studio.db /var/lib/studio-native/studio.db
sudo -u studio rm -f /var/lib/studio-native/studio.db-wal /var/lib/studio-native/studio.db-shm
sudo systemctl start studio-native
```

## Numa VPS que já roda Docker

Se a VPS já tem apps em compose atrás de um cloudflared compartilhado, o Studio
Native entra do mesmo jeito, sem instalar nada na máquina. O repositório traz
[`Dockerfile`](../Dockerfile), [`deploy/compose.yml`](../deploy/compose.yml) e um
workflow que publica a imagem no GHCR a cada release.

A imagem tem o ffmpeg e a fonte de emoji dentro, roda como um usuário sem
privilégios (uid 10001) e serve na porta 5050. Antes do primeiro deploy, na VPS:

```bash
sudo install -d -o 10001 -g 10001 -m 700 /srv/apps/studio-native/data
sudo sh -c 'head -c 32 /dev/urandom > /srv/apps/studio-native/token.key'
sudo chown 10001:10001 /srv/apps/studio-native/token.key && sudo chmod 400 /srv/apps/studio-native/token.key
printf 'STUDIO_PUBLIC_URL=https://native.toffa.com.br\n' | sudo tee /srv/apps/studio-native/app.env
```

O `data/` e o `token.key` precisam ser do uid 10001 porque o container não roda
como root. A chave fica fora de `data/` de propósito: um backup da pasta de
dados não leva a chave junto.

Depois, com a imagem publicada, o deploy é o mesmo dos outros apps — no
prod-01, `/srv/infra/scripts/deploy.sh`, que sobe a versão nova e volta sozinho
para a anterior se o healthcheck falhar. Na Cloudflare, o hostname aponta para
`http://studio-native:5050`, pela rede `edge`.

Duas diferenças em relação ao systemd: os dados ficam em
`/srv/apps/studio-native/data` (e não em `/var/lib/studio-native`), e o
`STUDIO_TRUSTED_PROXIES` precisa cobrir a rede do Docker, senão o app vê todos
os visitantes com o mesmo IP.

## Swap

Em VPS com pouca memória, um render pode estourar a RAM, e o kernel mata o
processo (o systemd sobe de novo, mas a geração em andamento se perde). 2 GB de
swap dão margem:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Comandos do dia a dia

```bash
systemctl status studio-native
sudo systemctl restart studio-native
journalctl -u studio-native -f            # log ao vivo
journalctl -u studio-native -n 100        # últimas 100 linhas
systemctl list-timers studio-native-backup
```

## Quando algo dá errado

**502 no endereço público.** O serviço está parado (`systemctl status
studio-native`) ou o túnel aponta para `localhost` em vez de `127.0.0.1`.

**O serviço não sobe e o log fala da chave dos tokens.** O
`/etc/studio-native/token.key` precisa ter 32 bytes: crus, em base64 ou em hex.
Gere outro com `sudo sh -c 'head -c 32 /dev/urandom > /etc/studio-native/token.key'`
e reconecte as contas do TikTok.

**O login do TikTok volta com erro de `redirect_uri`.** O `STUDIO_PUBLIC_URL`
não bate com o registrado no portal do TikTok e no `ALLOWED_REDIRECTS` do
Worker, ou o túnel não é o da própria VPS (veja "O desenho").

**Faço login e a tela de senha volta.** Você está entrando por `http://`. Com
`STUDIO_COOKIE_SECURE=1`, o navegador não guarda o cookie sem HTTPS. Use o
endereço público.

**Geração parada em "Aguardando vaga...".** Outro render está em andamento, e
`STUDIO_RENDER_SLOTS` limita quantos rodam juntos. Se a máquina aguenta mais,
suba o número.

**O processo morreu no meio de um render.** Veja se foi falta de memória com
`journalctl -k | grep -i oom`. Se foi: swap, ou `STUDIO_RENDER_SLOTS=1`.
