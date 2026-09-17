#!/usr/bin/env bash
# Backup do Studio Native. Roda todo dia pelo studio-native-backup.timer, como
# o usuario `studio`; manualmente: sudo systemctl start studio-native-backup
#
# Sempre: copia consistente do studio.db (API de backup do SQLite, segura com o
# app rodando) mais config.json e library.json, em /var/backups/studio-native,
# guardando as ultimas 14.
#
# Com RCLONE_REMOTE definido em /etc/studio-native/backup.env: manda essa copia
# e os videos para o remoto. E o que importa de verdade -- backup que mora no
# mesmo disco da VPS nao sobrevive a perda dele.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DADOS="${STUDIO_DATA_DIR:-/var/lib/studio-native}"
DESTINO="${BACKUP_DIR:-/var/backups/studio-native}"
MANTER="${BACKUP_MANTER:-14}"

carimbo="$(date +%Y%m%d-%H%M%S)"
pasta="$DESTINO/$carimbo"
mkdir -p "$pasta"

"$APP_DIR/.venv/bin/python" - "$DADOS/studio.db" "$pasta/studio.db" <<'PY'
import sqlite3
import sys

origem = sqlite3.connect(sys.argv[1])
destino = sqlite3.connect(sys.argv[2])
origem.backup(destino)
destino.close()
origem.close()
PY
for arquivo in config.json library.json; do
  if [[ -f "$DADOS/$arquivo" ]]; then
    cp -p "$DADOS/$arquivo" "$pasta/$arquivo"
  fi
done
echo "Copia local: $pasta"

# Mantem so as ultimas $MANTER copias (os nomes sao datas, a ordem alfabetica
# e a cronologica).
find "$DESTINO" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | head -n -"$MANTER" | xargs -r rm -rf --

if [[ -z "${RCLONE_REMOTE:-}" ]]; then
  echo "Sem RCLONE_REMOTE: os videos ficam so no disco desta VPS."
  exit 0
fi
if ! command -v rclone >/dev/null; then
  echo "RCLONE_REMOTE definido, mas o rclone nao esta instalado (sudo apt install rclone)." >&2
  exit 1
fi

opcoes=()
if [[ -f /etc/studio-native/rclone.conf ]]; then
  opcoes=(--config /etc/studio-native/rclone.conf)
fi

rclone "${opcoes[@]}" copy "$pasta" "$RCLONE_REMOTE/banco/$carimbo"
for sub in library library_thumbs outputs; do
  [[ -d "$DADOS/$sub" ]] || continue
  # sync espelha a pasta, mas com --backup-dir o que sumiu daqui (um video
  # apagado por engano) vai para apagados/<data> no remoto em vez de sumir la.
  rclone "${opcoes[@]}" sync "$DADOS/$sub" "$RCLONE_REMOTE/arquivos/$sub" \
    --backup-dir "$RCLONE_REMOTE/apagados/$carimbo/$sub"
done
echo "Enviado para $RCLONE_REMOTE"
