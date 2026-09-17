#!/usr/bin/env bash
# Atualiza o Studio Native na VPS: codigo, dependencias, front e servico.
# E o equivalente do tools/atualizar.ps1 do Windows.
#
#   /opt/studio-native/tools/atualizar.sh            # puxa do git e atualiza
#   /opt/studio-native/tools/atualizar.sh --sem-git  # so reconstroi e reinicia
#
# Rode como o dono do repositorio, nao como root: o sudo so entra para reiniciar
# o servico. Se qualquer passo antes disso falhar, o servico NAO e reiniciado e
# continua servindo a versao que funcionava.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=tools/vps-comum.sh
source "$APP_DIR/tools/vps-comum.sh"

SEM_GIT=0
for arg in "$@"; do
  case "$arg" in
    --sem-git) SEM_GIT=1 ;;
    *)
      erro "Opcao desconhecida: $arg"
      exit 2
      ;;
  esac
done

DONO="$(stat -c %U "$APP_DIR")"
if [[ "$(id -un)" != "$DONO" ]]; then
  erro "Rode como '$DONO', o dono de $APP_DIR (sem sudo)."
  exit 1
fi
cd "$APP_DIR"

if [[ "$SEM_GIT" -eq 0 ]]; then
  passo "Codigo"
  # Alteracao local seria atropelada por um pull, e o erro so apareceria la na
  # frente, como um build estranho.
  if [[ -n "$(git status --porcelain)" ]]; then
    git status --short
    erro "Ha alteracoes nao commitadas. Commite ou descarte antes (ou use --sem-git)."
    exit 1
  fi
  if ! git rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
    erro "O ramo '$(git rev-parse --abbrev-ref HEAD)' nao acompanha nenhum remoto."
    exit 1
  fi
  git pull --ff-only
fi

passo "Dependencias do Python"
instalar_python "$APP_DIR"

passo "Front"
construir_front "$APP_DIR"

passo "Reiniciando o servico"
sudo systemctl restart studio-native

passo "Esperando responder"
if esperar_no_ar; then
  echo "Atualizado e no ar (commit $(git rev-parse --short HEAD))."
else
  erro "O servico nao respondeu em 30s. Veja o motivo com: journalctl -u studio-native -n 50"
  exit 1
fi

# A unidade instalada e gerada a partir de deploy/. Se o repositorio mudou a
# dela, reiniciar nao basta: o instalador precisa rodar de novo.
if ! gerar_unidade "$APP_DIR" | cmp -s - /etc/systemd/system/studio-native.service; then
  aviso "deploy/studio-native.service mudou. Para aplicar: sudo $APP_DIR/tools/instalar-vps.sh"
fi
