#!/usr/bin/env bash
# Instala o Studio Native numa VPS Linux com apt (Debian/Ubuntu) e systemd.
#
#   sudo git clone https://github.com/foffano/studio-native.git /opt/studio-native
#   sudo /opt/studio-native/tools/instalar-vps.sh
#
# Pode rodar de novo quantas vezes quiser -- e assim que se aplica uma mudanca em
# deploy/. Chave e configuracao que ja existem nunca sao sobrescritas.
#
# O que faz:
#   1. pacotes: Python, ffmpeg, fonte de emoji e fonte de texto de reserva
#   2. Node.js que sirva ao Vite 8, baixado do nodejs.org se faltar
#   3. usuario de sistema `studio`, dono so dos dados
#   4. venv do Python e build do front, como o dono do repositorio
#   5. /etc/studio-native: chave dos tokens e arquivo de ambiente
#   6. servico e backup diario no systemd, de pe e conferidos
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tools/vps-comum.sh
source "$APP_DIR/tools/vps-comum.sh"

USUARIO=studio
DADOS=/var/lib/studio-native
BACKUPS=/var/backups/studio-native
ETC=/etc/studio-native

if [[ $EUID -ne 0 ]]; then
  erro "Rode com sudo."
  exit 1
fi
if ! command -v apt-get >/dev/null || ! command -v systemctl >/dev/null; then
  erro "Este instalador precisa de apt (Debian/Ubuntu) e systemd."
  exit 1
fi
case "$APP_DIR" in
  /root/* | /home/*)
    erro "O repositorio esta em $APP_DIR. O servico roda como '$USUARIO' e nao enxerga pastas pessoais: clone em /opt/studio-native."
    exit 1
    ;;
esac

# O venv e o build sao do dono do repositorio, nao do root. Senao o proximo
# `git pull` dele esbarraria em arquivos que nao pode sobrescrever.
DONO="$(stat -c %U "$APP_DIR")"
como_dono() {
  local funcao="$1" casa roteiro
  # Aspas simples de proposito: quem expande $1 e $2 e o bash de dentro, que
  # recebe o caminho do repositorio e o nome da funcao como argumentos.
  # shellcheck disable=SC2016
  roteiro='set -euo pipefail; source "$1/tools/vps-comum.sh"; "$2" "$1"'
  if [[ "$DONO" == root ]]; then
    bash -c "$roteiro" _ "$APP_DIR" "$funcao"
    return
  fi
  casa="$(getent passwd "$DONO" | cut -d: -f6)"
  runuser -u "$DONO" -- env HOME="${casa:-/tmp}" PATH="$PATH" \
    bash -c "$roteiro" _ "$APP_DIR" "$funcao"
}

instalar_node_oficial() {
  local arquitetura base temp arquivo destino
  case "$(uname -m)" in
    x86_64) arquitetura=x64 ;;
    aarch64 | arm64) arquitetura=arm64 ;;
    *)
      erro "Nao ha Node oficial para $(uname -m). Instale Node 22.12+ e rode de novo."
      exit 1
      ;;
  esac
  # Linha LTS. O SHASUMS256.txt vem do mesmo lugar: protege de download
  # corrompido, que e o que da para proteger sem trazer GPG para o meio.
  base="https://nodejs.org/dist/latest-v24.x"
  temp="$(mktemp -d)"
  curl -fsSL "$base/SHASUMS256.txt" -o "$temp/SHASUMS256.txt"
  arquivo="$(grep -m 1 -oE "node-v[0-9.]+-linux-${arquitetura}\.tar\.xz" "$temp/SHASUMS256.txt")"
  curl -fsSL "$base/$arquivo" -o "$temp/$arquivo"
  (cd "$temp" && grep " ${arquivo}\$" SHASUMS256.txt | sha256sum -c --quiet -)
  destino="/opt/nodejs/${arquivo%.tar.xz}"
  mkdir -p /opt/nodejs
  rm -rf "$destino"
  tar -xJf "$temp/$arquivo" -C /opt/nodejs
  ln -sfn "$destino" /opt/nodejs/atual
  for b in node npm npx; do
    ln -sfn "/opt/nodejs/atual/bin/$b" "/usr/local/bin/$b"
  done
  rm -rf "$temp"
}

passo "Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv ffmpeg fonts-noto-color-emoji fonts-dejavu-core \
  git curl ca-certificates xz-utils >/dev/null
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  erro "Precisa de Python 3.10 ou mais novo (este e $(python3 --version))."
  exit 1
fi

passo "Node.js"
if node_serve; then
  echo "Node $(node -v) ja serve."
else
  echo "Baixando o Node LTS oficial do nodejs.org..."
  instalar_node_oficial
  echo "Node $(node -v) instalado em /opt/nodejs."
fi

passo "Usuario e pastas"
if ! id -u "$USUARIO" >/dev/null 2>&1; then
  useradd --system --home-dir "$DADOS" --no-create-home --shell /usr/sbin/nologin "$USUARIO"
fi
install -d -o "$USUARIO" -g "$USUARIO" -m 0700 "$DADOS" "$BACKUPS"
install -d -o root -g root -m 0755 "$ETC"
if ! runuser -u "$USUARIO" -- test -r "$APP_DIR/app.py"; then
  erro "O usuario '$USUARIO' nao consegue ler $APP_DIR. Libere a leitura: chmod -R o+rX $APP_DIR"
  exit 1
fi

passo "Chave dos tokens e configuracao"
if [[ ! -s "$ETC/token.key" ]]; then
  (umask 077 && head -c 32 /dev/urandom >"$ETC/token.key")
  echo "Chave nova em $ETC/token.key. Guarde uma copia fora da VPS: sem ela, as contas do TikTok precisam ser reconectadas."
fi
if [[ ! -f "$ETC/studio-native.env" ]]; then
  install -m 0600 -o root -g root "$APP_DIR/deploy/studio-native.env.example" "$ETC/studio-native.env"
  echo "Configuracao criada em $ETC/studio-native.env -- confira o STUDIO_PUBLIC_URL."
fi

passo "Dependencias do Python"
como_dono instalar_python

passo "Front"
como_dono construir_front

passo "Servico do systemd"
VERSAO_SYSTEMD="$(systemctl --version | awk 'NR == 1 { print $2 }')"
if [[ "$VERSAO_SYSTEMD" -ge 247 ]]; then
  chown root:root "$ETC/token.key"
  chmod 0600 "$ETC/token.key"
else
  aviso "systemd $VERSAO_SYSTEMD nao tem LoadCredential: a chave fica legivel pelo grupo '$USUARIO'."
  chown root:"$USUARIO" "$ETC/token.key"
  chmod 0640 "$ETC/token.key"
fi
gerar_unidade "$APP_DIR" >/etc/systemd/system/studio-native.service
sed "s#/opt/studio-native#${APP_DIR}#g" "$APP_DIR/deploy/studio-native-backup.service" \
  >/etc/systemd/system/studio-native-backup.service
install -m 0644 "$APP_DIR/deploy/studio-native-backup.timer" /etc/systemd/system/studio-native-backup.timer
systemctl daemon-reload
systemctl enable --quiet studio-native
systemctl enable --quiet --now studio-native-backup.timer
systemctl restart studio-native

passo "Conferindo"
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q zscale; then
  aviso "O ffmpeg instalado nao tem o filtro zscale: video HDR de iPhone vai sair com cores lavadas."
fi
if [[ ! -f /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf ]]; then
  aviso "Fonte de emoji nao encontrada: os emojis vao ser omitidos das frases."
fi
MEMORIA_MB="$(awk '/^MemTotal/ { print int($2 / 1024) }' /proc/meminfo)"
SWAP_MB="$(awk '/^SwapTotal/ { print int($2 / 1024) }' /proc/meminfo)"
if [[ "$MEMORIA_MB" -lt 3500 && "$SWAP_MB" -eq 0 ]]; then
  aviso "A VPS tem ${MEMORIA_MB} MB de RAM e nenhum swap. Um render pode estourar a memoria; veja 'Swap' em docs/vps-linux.md."
fi

if esperar_no_ar; then
  echo "Studio Native no ar em http://127.0.0.1:$(valor_do_env STUDIO_PORT 5050)"
else
  erro "O servico nao respondeu em 30s. Veja o motivo com: journalctl -u studio-native -n 50"
  exit 1
fi

cat <<EOF

Pronto. Falta (detalhes em docs/vps-linux.md):
  1. Conferir $ETC/studio-native.env e, se mudar algo: sudo systemctl restart studio-native
  2. Apontar o tunel da Cloudflare para http://127.0.0.1:$(valor_do_env STUDIO_PORT 5050)
  3. Trazer os dados do Windows (tools/exportar-para-vps.ps1 la, tools/importar-dados.sh aqui)
  4. Reconectar as contas do TikTok em Ajustes
  5. Guardar uma copia de $ETC/token.key fora da VPS
EOF
