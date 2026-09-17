# Funcoes compartilhadas pelos scripts da VPS (instalar-vps.sh, atualizar.sh,
# importar-dados.sh). Nao e para rodar sozinho: e carregado com `source`.

passo() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*" >&2; }
erro() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; }

ENV_FILE=/etc/studio-native/studio-native.env

# Valor de uma variavel do arquivo de ambiente, ou o padrao. Quem nao e root
# nao le o arquivo (0600), e fica com o padrao -- que e o que o instalador poe.
valor_do_env() {
  local nome="$1" padrao="$2" valor=""
  if [[ -r "$ENV_FILE" ]]; then
    valor="$(sed -n "s/^${nome}=//p" "$ENV_FILE" | tail -n 1)"
  fi
  echo "${valor:-$padrao}"
}

# Espera o app responder no /api/health (ate 30s).
esperar_no_ar() {
  local url
  url="http://127.0.0.1:$(valor_do_env STUDIO_PORT 5050)/api/health"
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Node que serve para o Vite 8: ^20.19.0 || >=22.12.0.
node_serve() {
  command -v node >/dev/null 2>&1 || return 1
  local versao maior menor
  versao="$(node -p 'process.versions.node' 2>/dev/null)" || return 1
  maior="${versao%%.*}"
  menor="${versao#*.}"
  menor="${menor%%.*}"
  if [[ "$maior" -eq 20 ]]; then
    [[ "$menor" -ge 19 ]]
  elif [[ "$maior" -eq 22 ]]; then
    [[ "$menor" -ge 12 ]]
  else
    [[ "$maior" -gt 22 ]]
  fi
}

# As funcoes abaixo param no primeiro erro por conta propria (`|| return 1`),
# sem depender de `set -e` em quem chama: o instalador as roda por `bash -c`.

# Dependencias do Python no venv do repositorio (cria o venv se faltar).
instalar_python() {
  local app="$1"
  if [[ ! -x "$app/.venv/bin/python" ]]; then
    python3 -m venv "$app/.venv" || return 1
  fi
  "$app/.venv/bin/pip" install -q --upgrade pip || return 1
  "$app/.venv/bin/pip" install -q -r "$app/requirements.txt" || return 1
  # Pre-compila agora: o servico roda com o codigo somente leitura e nao
  # conseguiria gravar o __pycache__ sozinho.
  "$app/.venv/bin/python" -m compileall -q "$app"/*.py >/dev/null || return 1
}

# Constroi o front numa pasta nova e so a troca pela atual se o build passou.
# O Flask serve desktop/dist direto: construir por cima dela deixaria o site
# sem interface durante o build -- e sem interface de vez, se o build falhasse.
construir_front() {
  local desktop="$1/desktop"
  rm -rf "$desktop/dist.novo"
  (cd "$desktop" &&
    npm ci --no-audit --no-fund --loglevel=error &&
    npm run build -- --outDir dist.novo --emptyOutDir) || return 1
  [[ -f "$desktop/dist.novo/index.html" ]] || return 1

  rm -rf "$desktop/dist.antigo"
  if [[ -d "$desktop/dist" ]]; then
    mv "$desktop/dist" "$desktop/dist.antigo" || return 1
  fi
  if ! mv "$desktop/dist.novo" "$desktop/dist"; then
    # Devolve o front que funcionava antes de desistir.
    mv "$desktop/dist.antigo" "$desktop/dist"
    return 1
  fi
  rm -rf "$desktop/dist.antigo"
}

# A unidade do systemd para este repositorio, ajustada a versao do systemd.
# Sem LoadCredential (systemd < 247), a chave vai por caminho explicito.
gerar_unidade() {
  local app="$1" versao
  versao="$(systemctl --version | awk 'NR == 1 { print $2 }')"
  if [[ "$versao" -ge 247 ]]; then
    sed "s#/opt/studio-native#${app}#g" "$app/deploy/studio-native.service"
  else
    sed -e "s#/opt/studio-native#${app}#g" \
      -e 's#^LoadCredential=token-key:\(.*\)#Environment=STUDIO_TOKEN_KEY_FILE=\1#' \
      "$app/deploy/studio-native.service"
  fi
}
