#!/usr/bin/env bash
# Coloca na VPS os dados exportados do Windows por tools/exportar-para-vps.ps1.
#
#   sudo /opt/studio-native/tools/importar-dados.sh /tmp/studio-dados.tar.gz
#
# Para o servico, guarda a pasta de dados atual ao lado (nada e apagado), extrai,
# acerta dono e permissoes e sobe de novo. Vem junto: senha de acesso, chaves de
# API, vozes, Biblioteca, videos produzidos e o catalogo. Nao vem: os tokens do
# TikTok -- cifrados com o DPAPI do Windows, eles nao abrem aqui, e as contas
# precisam ser reconectadas uma vez.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tools/vps-comum.sh
source "$APP_DIR/tools/vps-comum.sh"

USUARIO=studio

if [[ $EUID -ne 0 ]]; then
  erro "Rode com sudo."
  exit 1
fi
ARQUIVO="${1:-}"
if [[ ! -f "$ARQUIVO" ]]; then
  erro "Uso: sudo $0 studio-dados.tar.gz"
  exit 2
fi

DADOS="$(valor_do_env STUDIO_DATA_DIR /var/lib/studio-native)"
if [[ "$DADOS" != /* || "$DADOS" == / ]]; then
  erro "STUDIO_DATA_DIR invalido: '$DADOS'."
  exit 1
fi

TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT

passo "Abrindo o arquivo"
tar -xzf "$ARQUIVO" -C "$TEMP"
ORIGEM="$TEMP/StudioNative"
[[ -d "$ORIGEM" ]] || ORIGEM="$TEMP"
if [[ ! -f "$ORIGEM/config.json" && ! -f "$ORIGEM/studio.db" ]]; then
  erro "O arquivo nao parece a pasta de dados do Studio Native (nao tem config.json nem studio.db)."
  exit 1
fi

passo "Parando o servico"
systemctl stop studio-native 2>/dev/null || true

if [[ -d "$DADOS" && -n "$(ls -A "$DADOS")" ]]; then
  GUARDADA="${DADOS}.antes-da-importacao-$(date +%Y%m%d-%H%M%S)"
  echo "Os dados que estavam aqui ficam em $GUARDADA"
  mv "$DADOS" "$GUARDADA"
fi
install -d -o "$USUARIO" -g "$USUARIO" -m 0700 "$DADOS"

passo "Copiando"
# O studio.db-wal vem junto de proposito: o app do Windows foi parado a forca, e
# as ultimas gravacoes podem estar so nele. O SQLite as aplica ao abrir.
cp -a "$ORIGEM"/. "$DADOS"/
# Temporarios de uma maquina nao servem na outra.
rm -rf "$DADOS/uploads" "$DADOS/library_staging" "$DADOS/tmp"
chown -R "$USUARIO:$USUARIO" "$DADOS"
chmod -R u+rwX,go-rwx "$DADOS"

passo "Subindo"
systemctl start studio-native
if ! esperar_no_ar; then
  erro "O servico nao respondeu em 30s. Veja o motivo com: journalctl -u studio-native -n 50"
  exit 1
fi

contar() { find "$1" -maxdepth 1 -type f -name "$2" 2>/dev/null | wc -l | tr -d ' '; }
cat <<EOF

Importado:
  videos na Biblioteca: $(contar "$DADOS/library" '*.mp4')
  videos produzidos:    $(contar "$DADOS/outputs" '*.mp4')

Entre pelo endereco publico com a senha de sempre e reconecte as contas do
TikTok em Ajustes.
EOF
