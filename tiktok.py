"""Conectar a conta do TikTok (Login Kit v2 com PKCE).

O fluxo inteiro, em ordem:

1. O app pergunta ao Worker qual e o `client_key` (ele nao viaja no .exe).
2. Geramos `code_verifier`/`code_challenge` (PKCE) e um `state`.
3. Subimos um servidor descartavel em 127.0.0.1:43117 e abrimos o navegador
   do sistema na tela de autorizacao do TikTok.
4. O TikTok devolve o usuario para `http://127.0.0.1:43117/api/tiktok/callback`.
5. Trocamos o `code` por token **atraves do Worker**, que e quem guarda o
   `client_secret`.
6. Buscamos apelido e avatar (`user.info.basic`) e gravamos a conta, com os
   tokens cifrados.

## Dois caminhos de volta, e por que

O TikTok precisa devolver o usuario para algum lugar depois da autorizacao.

- **Do PC**: `http://127.0.0.1:43117/api/tiktok/callback`, atendido por um
  servidor descartavel que sobe so durante o login.
- **De fora** (celular, pelo tunel): o loopback nao serve -- `127.0.0.1` no
  telefone e o proprio telefone, que nao tem nada escutando. Ai o retorno vai
  para a URL publica do app, e quem atende e uma rota normal do Flask.

Quem decide e a origem do pedido: se voce clicou em "Conectar" a partir de
`https://native.toffa.com.br`, o retorno vai para la. Os dois precisam estar
registrados no portal do TikTok e na allowlist do Worker.

## Por que 43117 nao e a porta do backend

O backend subia numa porta sorteada quando havia Electron. Fixar em 43117
significaria o app nao abrir quando qualquer outra coisa estivesse usando a
porta -- um modo de falha permanente para resolver um problema de trinta
segundos. O listener daqui vive so durante o login e morre em seguida.

## O erro que o TikTok esconde

`POST /tiktok/token` responde **HTTP 200 mesmo recusando** a troca; o problema
vem no corpo, em `error`. Quem olha so o status acha que conectou e guarda uma
sessao morta. Por isso toda resposta passa por `_unwrap()`.
"""

import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import secretbox
import store

AUTH_SERVICE = os.getenv("STUDIO_TIKTOK_AUTH_URL", "https://auth.toffa.com.br").rstrip("/")

LOOPBACK_PORT = 43117
CALLBACK_PATH = "/api/tiktok/callback"
REDIRECT_URI = f"http://127.0.0.1:{LOOPBACK_PORT}{CALLBACK_PATH}"


def redirect_para(origem=None):
    """Escolhe o endereco de retorno a partir de onde o pedido veio.

    `origem` e a `request.host_url` do Flask. Quando ela aponta para um endereco
    publico, o retorno vai para la; do contrario, para o loopback. Comparar com
    "localhost"/"127.0.0.1" e o suficiente porque so existem esses dois casos.
    """
    if not origem:
        return REDIRECT_URI
    base = origem.rstrip("/")
    if "://127.0.0.1" in base or "://localhost" in base:
        return REDIRECT_URI
    return f"{base}{CALLBACK_PATH}"

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

# O usuario tem 5 minutos para concluir o login. Passou disso, o listener cai
# sozinho -- deixar uma porta aberta esperando para sempre e como o app trava.
FLOW_TIMEOUT = 300

# Renova o token com folga. O access token dura 24h; 30 minutos de margem
# cobrem o relogio local errado e uma publicacao longa comecada perto do fim.
REFRESH_MARGIN = 1800

HTTP_TIMEOUT = 20


class TikTokError(Exception):
    """Erro que ja esta em portugues e pode ser mostrado ao usuario."""


# ---------------------------------------------------------------------------
# Estado do fluxo em andamento
# ---------------------------------------------------------------------------
# Um login por vez, de proposito: dois fluxos simultaneos disputariam a porta
# 43117 e o segundo `state` invalidaria o primeiro.
_LOCK = threading.Lock()
_FLOW = None
_SERVER = None
_THREAD = None


def _stop_flow():
    """Encerra o login em andamento e so retorna com a porta ja liberada.

    Nao use `HTTPServer.shutdown()` aqui: ele so termina um `serve_forever()`,
    e o laco abaixo e feito de `handle_request()`. Chamado sobre este servidor,
    `shutdown()` espera para sempre por um evento que ninguem vai disparar --
    e trava segurando o lock, o que derruba o backend inteiro.

    O sinal correto e zerar `_FLOW`: `_serve()` ve isso no proximo giro (no
    maximo 1s, o timeout do handle_request), sai do laco e fecha o socket.
    O join espera exatamente isso, porque quem clica em "conectar" duas vezes
    seguidas tentaria abrir a 43117 antes de a anterior soltar.
    """
    global _FLOW, _SERVER, _THREAD
    with _LOCK:
        _FLOW = None
        server, thread = _SERVER, _THREAD
        _SERVER = _THREAD = None

    # Fora do lock, de proposito: _serve() precisa dele para terminar.
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)
    if server is not None:
        try:
            server.server_close()
        except Exception:  # noqa: BLE001
            pass


def _set_flow(**fields):
    with _LOCK:
        if _FLOW is not None:
            _FLOW.update(fields)


def flow_status():
    """Snapshot do login em andamento, para a UI fazer polling."""
    with _LOCK:
        if _FLOW is None:
            return {"state": "ocioso"}
        return {
            "state": _FLOW["status"],
            "error": _FLOW.get("error", ""),
            "expira_em": max(0, int(_FLOW["deadline"] - time.time())),
        }


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

def _pkce():
    """Gera o par verifier/challenge.

    PKCE existe justamente para o caso desktop: sem ele, quem interceptasse o
    `code` no redirect em loopback trocaria por token sozinho. O verifier nunca
    sai desta maquina -- so o hash dele viaja na URL.

    **O challenge e HEX, nao base64url.** A RFC 7636 manda
    `BASE64URL(SHA256(verifier))`, e e isso que toda biblioteca de OAuth faz por
    padrao -- mas o TikTok documenta `HEX(SHA256(verifier))` para Desktop, com
    exemplo em `CryptoJS.enc.Hex`. Usar o padrao aqui passa reto na tela de
    autorizacao e so falha depois, na troca do code, com um erro que nao diz
    nada sobre encoding.

    O alfabeto do `token_urlsafe` (A-Z a-z 0-9 - _) ja esta dentro dos
    caracteres nao reservados que o TikTok exige.
    """
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    return verifier, challenge


# ---------------------------------------------------------------------------
# Conversas com o Worker e com o TikTok
# ---------------------------------------------------------------------------

def _unwrap(res, contexto):
    """Le a resposta do Worker tratando o 200-com-erro do TikTok."""
    try:
        data = res.json()
    except ValueError:
        raise TikTokError(f"{contexto}: resposta invalida do servico de autenticacao")

    if isinstance(data, dict) and data.get("error"):
        detalhe = data.get("error_description") or data.get("message") or data["error"]
        raise TikTokError(f"{contexto}: {detalhe}")

    if not res.ok:
        raise TikTokError(f"{contexto}: erro {res.status_code}")

    return data


def service_config():
    """client_key, escopos e redirect, vindos do Worker."""
    try:
        res = requests.get(f"{AUTH_SERVICE}/tiktok/client-key", timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise TikTokError(f"Nao foi possivel falar com o servico de autenticacao: {e}")
    data = _unwrap(res, "Configuracao")
    if not data.get("client_key"):
        raise TikTokError("O servico de autenticacao nao devolveu o client_key")
    return data


def _exchange(path, payload, contexto):
    try:
        res = requests.post(
            f"{AUTH_SERVICE}{path}", json=payload, timeout=HTTP_TIMEOUT
        )
    except requests.RequestException as e:
        raise TikTokError(f"{contexto}: falha de rede ({e})")
    return _unwrap(res, contexto)


def fetch_user_info(access_token):
    """Apelido e avatar da conta conectada (escopo user.info.basic).

    Nao e enfeite: a tela de publicacao precisa mostrar para qual conta o video
    vai, e o TikTok reprova a revisao quando o destino nao esta visivel.
    """
    try:
        res = requests.get(
            USER_INFO_URL,
            params={"fields": "open_id,display_name,avatar_url"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT,
        )
        data = res.json()
    except (requests.RequestException, ValueError) as e:
        raise TikTokError(f"Nao foi possivel ler os dados da conta: {e}")

    erro = (data.get("error") or {}) if isinstance(data, dict) else {}
    # O TikTok manda `error.code == "ok"` no caminho feliz -- ausencia de erro
    # nao basta como sinal de sucesso.
    if erro and erro.get("code") not in ("ok", "", None):
        raise TikTokError(
            f"Nao foi possivel ler os dados da conta: {erro.get('message') or erro.get('code')}"
        )

    user = ((data.get("data") or {}).get("user") or {}) if isinstance(data, dict) else {}
    return {
        "open_id": user.get("open_id") or "",
        "nickname": user.get("display_name") or "",
        "avatar_url": user.get("avatar_url") or "",
    }


# ---------------------------------------------------------------------------
# Gravacao da conta
# ---------------------------------------------------------------------------

def _save_account(tokens):
    """Troca concluida -> conta no banco, com os tokens cifrados."""
    access = tokens.get("access_token") or ""
    if not access:
        raise TikTokError("O TikTok nao devolveu access_token")

    info = fetch_user_info(access)
    open_id = info["open_id"] or tokens.get("open_id") or ""
    if not open_id:
        raise TikTokError("O TikTok nao identificou a conta (open_id ausente)")

    try:
        expira = int(tokens.get("expires_in") or 0)
    except (TypeError, ValueError):
        expira = 0

    return store.upsert_account(
        platform="tiktok",
        open_id=open_id,
        nickname=info["nickname"],
        avatar_url=info["avatar_url"],
        access_token_enc=secretbox.encrypt(access),
        refresh_token_enc=secretbox.encrypt(tokens.get("refresh_token") or ""),
        expires_at=str(int(time.time()) + expira) if expira else "",
        scopes=tokens.get("scope") or "",
    )


# ---------------------------------------------------------------------------
# O listener descartavel
# ---------------------------------------------------------------------------

_PAGINA = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Studio Native</title>
<style>
 body{{font:16px/1.6 system-ui,sans-serif;background:#0e1726;color:#e6edf7;
      display:grid;place-items:center;height:100vh;margin:0;text-align:center}}
 .c{{max-width:30rem;padding:2rem}} h1{{font-size:1.4rem;margin:0 0 .5rem}}
 .ok{{color:#4ade80}} .bad{{color:#f87171}} p{{color:#9fb0c8;margin:.4rem 0}}
 .btn{{display:inline-block;margin-top:1.2rem;padding:.75rem 1.5rem;border-radius:10px;
       background:#2563eb;color:#fff;text-decoration:none;font-weight:600}}
</style>
<div class="c"><h1 class="{cls}">{titulo}</h1><p>{texto}</p>
<a class="btn" href="/">Voltar ao Studio Native</a></div>"""


class _CallbackHandler(BaseHTTPRequestHandler):
    # Silencia o log do http.server: ele imprimiria a query string inteira no
    # stdout, e o `code` de autorizacao vai justamente ali.
    def log_message(self, *_args):
        pass

    def _responder(self, titulo, texto, cls):
        corpo = _PAGINA.format(titulo=titulo, texto=texto, cls=cls).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):  # noqa: N802 (assinatura do http.server)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        resultado = processar_callback(
            code=(params.get("code") or [""])[0],
            state=(params.get("state") or [""])[0],
            erro=(params.get("error") or [""])[0],
            redirect_uri=REDIRECT_URI,
        )
        self._responder(resultado["titulo"], resultado["texto"], resultado["classe"])


def processar_callback(code, state, erro, redirect_uri):
    """Conclui o login: confere o state, troca o code por token, grava a conta.

    Vive aqui, e nao dentro do handler, porque existem dois caminhos de volta --
    o loopback e a rota publica do Flask -- e duplicar esta logica seria duplicar
    a verificacao do `state`, que e justamente a parte que nao pode divergir.

    Devolve o que mostrar ao usuario; nao levanta excecao, porque quem chama
    esta sempre renderizando uma pagina para um navegador.
    """
    with _LOCK:
        fluxo = dict(_FLOW) if _FLOW else None

    if not fluxo:
        return {
            "ok": False,
            "titulo": "Login expirado",
            "texto": "Tente conectar de novo pelo app.",
            "classe": "bad",
        }

    # O `state` e a defesa contra alguem induzir o navegador a completar um
    # login que nao foi o usuario que comecou.
    if not state or not secrets.compare_digest(state, fluxo["state_token"]):
        _set_flow(status="erro", error="O state nao confere; login descartado.")
        return {
            "ok": False,
            "titulo": "Login recusado",
            "texto": "O state nao confere.",
            "classe": "bad",
        }

    if erro:
        _set_flow(status="erro", error=f"O TikTok recusou: {erro}")
        return {
            "ok": False,
            "titulo": "Autorizacao negada",
            "texto": f"O TikTok respondeu: {erro}",
            "classe": "bad",
        }

    if not code:
        _set_flow(status="erro", error="O TikTok nao devolveu o code.")
        return {
            "ok": False,
            "titulo": "Login incompleto",
            "texto": "Nenhum codigo recebido.",
            "classe": "bad",
        }

    try:
        tokens = _exchange(
            "/tiktok/token",
            {
                "code": code,
                "code_verifier": fluxo["verifier"],
                # Precisa ser byte a byte o mesmo que foi na autorizacao: o
                # TikTok confere, e usar o outro caminho de volta aqui derrubaria
                # a troca com um erro que nao explica nada.
                "redirect_uri": redirect_uri,
            },
            "Troca de token",
        )
        conta = _save_account(tokens)
    except TikTokError as e:
        _set_flow(status="erro", error=str(e))
        return {"ok": False, "titulo": "Nao deu certo", "texto": str(e), "classe": "bad"}

    _set_flow(status="conectado", account_id=conta["id"], error="")
    return {
        "ok": True,
        "titulo": "Conta conectada",
        "texto": f"@{conta.get('nickname') or 'conta'} esta ligada ao Studio Native.",
        "classe": "ok",
    }


def pagina_de_retorno(resultado):
    """HTML da pagina que o usuario ve ao voltar do TikTok."""
    return _PAGINA.format(
        titulo=resultado["titulo"],
        texto=resultado["texto"],
        cls=resultado["classe"],
    )


def _serve(server, deadline):
    """Atende ate a conta conectar, dar erro, ou o prazo acabar."""
    server.timeout = 1
    while time.time() < deadline:
        with _LOCK:
            terminou = _FLOW is None or _FLOW["status"] in ("conectado", "erro")
        if terminou:
            break
        server.handle_request()

    with _LOCK:
        if _FLOW is not None and _FLOW["status"] == "aguardando":
            _FLOW["status"] = "erro"
            _FLOW["error"] = "Tempo esgotado. Clique em conectar de novo."
    try:
        server.server_close()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# API usada pelas rotas do Flask
# ---------------------------------------------------------------------------

def start_connect(origem=None):
    """Prepara o login e devolve a URL de autorizacao para o app abrir.

    `origem` e a `request.host_url`: e ela que decide se o TikTok devolve o
    usuario para o loopback (acesso pelo PC) ou para a URL publica (celular).
    """
    global _FLOW, _SERVER, _THREAD

    config = service_config()
    redirect_uri = redirect_para(origem)
    pelo_loopback = redirect_uri == REDIRECT_URI

    _stop_flow()

    server = None
    if pelo_loopback:
        try:
            server = HTTPServer(("127.0.0.1", LOOPBACK_PORT), _CallbackHandler)
        except OSError as e:
            raise TikTokError(
                f"A porta {LOOPBACK_PORT} esta ocupada por outro programa, e o "
                f"TikTok exige exatamente ela no retorno do login. Feche o que "
                f"estiver usando a porta e tente de novo. ({e})"
            )

    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    deadline = time.time() + FLOW_TIMEOUT

    with _LOCK:
        # Dois conceitos, dois nomes: `status` e onde o login esta (aguardando,
        # conectado, erro) e `state_token` e o parametro `state` do OAuth. Usar
        # a mesma chave para os dois faria o handler comparar a coisa errada e
        # aceitar qualquer callback.
        _FLOW = {
            "status": "aguardando",
            "verifier": verifier,
            "state_token": state,
            "deadline": deadline,
            "error": "",
            # Guardado porque a troca do code exige o mesmo redirect_uri da
            # autorizacao, e quem conclui pode ser a rota do Flask.
            "redirect_uri": redirect_uri,
        }
        _SERVER = server
        if server is not None:
            _THREAD = threading.Thread(
                target=_serve, args=(server, deadline), daemon=True
            )
            _THREAD.start()

    query = urllib.parse.urlencode({
        "client_key": config["client_key"],
        "scope": config.get("scopes") or "user.info.basic,video.upload",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {
        "url": f"{AUTHORIZE_URL}?{query}",
        "expira_em": FLOW_TIMEOUT,
        "redirect_uri": redirect_uri,
        "pelo_loopback": pelo_loopback,
    }


def redirect_do_fluxo():
    """O redirect_uri do login em andamento, para a rota do Flask concluir."""
    with _LOCK:
        return (_FLOW or {}).get("redirect_uri") or REDIRECT_URI


def cancel_connect():
    _stop_flow()
    return {"state": "ocioso"}


# Quando a ultima tentativa de renovar a foto falhou. Sem isto, uma conta cuja
# foto nao pode ser renovada (rede fora, escopo revogado) faria uma chamada ao
# TikTok a cada leitura da tela de Ajustes.
_ultima_tentativa_avatar = 0.0
ESPERA_APOS_FALHA = 300  # 5 minutos


def _avatar_vencido(url):
    """A foto do TikTok vem numa URL assinada que vence -- em cerca de um dia.

    O app guardava essa URL na conexao e nunca mais mexia nela, entao a foto
    parava de aparecer no dia seguinte e parecia que a conta tinha caido. A
    conta esta perfeita; e a URL que envelhece.

    Vencido tambem quando falta pouco: a pagina pode ficar aberta por horas.
    """
    if not url:
        return True
    try:
        consulta = urllib.parse.urlparse(url).query
        expira = urllib.parse.parse_qs(consulta).get("x-expires", [""])[0]
        if not expira:
            return False  # sem carimbo, nao ha o que julgar -- deixa como esta
        return time.time() > int(expira) - 600
    except (ValueError, TypeError):
        return False


def current_account():
    """Conta conectada, sem nenhum token dentro.

    Renova a foto quando a URL dela venceu. E de proposito que isso acontece na
    leitura, e nao num relogio: ninguem precisa da foto enquanto ninguem olha.
    """
    global _ultima_tentativa_avatar
    conta = store.active_account("tiktok")

    if (
        conta
        and conta.get("access_token_enc")
        and _avatar_vencido(conta.get("avatar_url"))
        and time.time() - _ultima_tentativa_avatar > ESPERA_APOS_FALHA
    ):
        _ultima_tentativa_avatar = time.time()
        try:
            access, conta = valid_access_token()
            info = fetch_user_info(access)
            if info.get("avatar_url"):
                conta = store.set_account_avatar(conta["id"], info["avatar_url"])
        except Exception as e:  # noqa: BLE001
            # Amplo de proposito: falha aqui nao pode derrubar a tela. Sem foto
            # o app funciona inteiro, e dizer "conta desconectada" seria mentira.
            print(f"[StudioNative] nao deu para renovar a foto do TikTok: {e}", flush=True)

    return store.public_account(conta)


def disconnect():
    conta = store.active_account("tiktok")
    if not conta:
        return None
    return store.public_account(store.delete_account(conta["id"]))


def valid_access_token():
    """Access token utilizavel, renovando quando esta perto de vencer.

    Quem for publicar chama isto, nunca o banco direto: o token de 24h expira
    no meio de uma sessao de trabalho normal, e sem a renovacao automatica o
    usuario levaria "faca login de novo" no meio de um envio.
    """
    conta = store.active_account("tiktok")
    if not conta:
        raise TikTokError("Nenhuma conta do TikTok conectada.")

    access = secretbox.decrypt(conta.get("access_token_enc") or "")
    if not access:
        raise TikTokError(
            "Os tokens salvos nao podem ser lidos nesta maquina. Conecte a conta de novo."
        )

    try:
        expira_em = int(conta.get("expires_at") or 0)
    except (TypeError, ValueError):
        expira_em = 0

    if expira_em and time.time() < expira_em - REFRESH_MARGIN:
        return access, conta

    refresh = secretbox.decrypt(conta.get("refresh_token_enc") or "")
    if not refresh:
        raise TikTokError("Sessao expirada e sem refresh token. Conecte a conta de novo.")

    tokens = _exchange("/tiktok/refresh", {"refresh_token": refresh}, "Renovacao de sessao")
    novo = tokens.get("access_token") or ""
    if not novo:
        raise TikTokError("A renovacao nao devolveu access_token. Conecte a conta de novo.")

    try:
        dura = int(tokens.get("expires_in") or 0)
    except (TypeError, ValueError):
        dura = 0

    campos = {
        "access_token_enc": secretbox.encrypt(novo),
        "expires_at": str(int(time.time()) + dura) if dura else "",
    }
    # O TikTok pode rotacionar o refresh token na renovacao. Guardar o antigo
    # deixaria a proxima renovacao falhar sem motivo aparente.
    if tokens.get("refresh_token"):
        campos["refresh_token_enc"] = secretbox.encrypt(tokens["refresh_token"])

    conta = store.update_account(conta["id"], **campos)
    return novo, conta


# ---------------------------------------------------------------------------
# Publicar nos rascunhos (Content Posting API)
# ---------------------------------------------------------------------------
# Caminho de rascunho, nao Direct Post. Dois motivos: o rascunho e o que permite
# o criador adicionar o produto (o "carrinho laranja") antes de publicar, e ele
# exige apenas `video.upload` -- o `video.publish` do Direct Post puxa a revisao
# mais rigida do TikTok.
#
# Consequencia pratica: **o `creator_info/query` nao entra aqui**. Ele so e
# obrigatorio no Direct Post e responde `scope_not_authorized` com o nosso
# token, porque exige `video.publish`. O plano original mandava chama-lo antes
# de mostrar a tela; seria uma parede.

INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

# Regras de fatiamento do TikTok. Cada pedaco tem que ter no minimo 5 MB e no
# maximo 64 MB -- exceto o ultimo, que absorve o resto e pode passar disso.
MIN_CHUNK = 5_000_000
MAX_CHUNK = 64_000_000
CHUNK_ALVO = 10_000_000

# Upload de video e lento e nao pode morrer por impaciencia do cliente.
UPLOAD_TIMEOUT = 600

MIMES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


def _api(url, token, payload=None):
    """Chamada ao TikTok que trata `error.code` em vez de confiar no status."""
    try:
        res = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload if payload is not None else None,
            timeout=HTTP_TIMEOUT,
        )
        data = res.json()
    except (requests.RequestException, ValueError) as e:
        raise TikTokError(f"Falha ao falar com o TikTok: {e}")

    erro = (data.get("error") or {}) if isinstance(data, dict) else {}
    codigo = erro.get("code")
    # `ok` e o sucesso explicito. Ausencia de erro nao serve como sinal: o
    # TikTok responde 200 com corpo de erro dentro.
    if codigo and codigo != "ok":
        raise TikTokError(
            f"{erro.get('message') or codigo} "
            f"(codigo {codigo}, log {erro.get('log_id') or 'sem id'})"
        )
    return data.get("data") or {}


def plan_chunks(video_size):
    """Decide (chunk_size, total_chunk_count) para um arquivo.

    Tres regras do TikTok, e a terceira e a que quebra implementacao ingenua:

    1. Video menor que 5 MB vai inteiro, com `chunk_size` igual ao tamanho.
    2. Cada pedaco fica entre 5 MB e 64 MB.
    3. `total_chunk_count` e o tamanho **dividido para baixo** pelo chunk_size --
       ou seja, o resto nao vira um pedaco extra: ele e engolido pelo ultimo,
       que por isso pode passar do chunk_size. Quem calcula com arredondamento
       para cima manda um pedaco a mais e o upload e recusado.
    """
    if video_size <= 0:
        raise TikTokError("O arquivo de video esta vazio.")
    if video_size < MIN_CHUNK:
        return video_size, 1

    chunk = min(CHUNK_ALVO, video_size)
    chunk = max(MIN_CHUNK, min(chunk, MAX_CHUNK))
    total = max(1, video_size // chunk)
    return chunk, total


def init_draft_upload(token, video_size):
    """Reserva o envio e devolve (publish_id, upload_url, chunk_size, total)."""
    chunk, total = plan_chunks(video_size)
    data = _api(
        INBOX_INIT_URL,
        token,
        {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk,
                "total_chunk_count": total,
            }
        },
    )
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not publish_id or not upload_url:
        raise TikTokError("O TikTok nao devolveu publish_id/upload_url.")
    return publish_id, upload_url, chunk, total


def upload_file(upload_url, path, chunk_size, total, video_size, progresso=None):
    """Envia o arquivo em pedacos, direto do disco do usuario para o TikTok.

    O MP4 nao passa por servidor nosso em momento nenhum -- e isso que mantem o
    Worker no plano gratuito e e o que a politica de privacidade publicada
    promete.
    """
    mime = MIMES.get(os.path.splitext(path)[1].lower(), "video/mp4")

    with open(path, "rb") as f:
        for i in range(total):
            inicio = i * chunk_size
            # O ultimo pedaco vai ate o fim do arquivo, engolindo o resto da
            # divisao. Nao e `inicio + chunk_size - 1`.
            fim = video_size - 1 if i == total - 1 else inicio + chunk_size - 1
            f.seek(inicio)
            corpo = f.read(fim - inicio + 1)

            try:
                res = requests.put(
                    upload_url,
                    data=corpo,
                    headers={
                        "Content-Type": mime,
                        "Content-Length": str(len(corpo)),
                        "Content-Range": f"bytes {inicio}-{fim}/{video_size}",
                    },
                    timeout=UPLOAD_TIMEOUT,
                )
            except requests.RequestException as e:
                raise TikTokError(f"Falha ao enviar o video: {e}")

            if res.status_code not in (200, 201, 206):
                raise TikTokError(
                    f"O TikTok recusou o pedaco {i + 1}/{total} "
                    f"(HTTP {res.status_code})"
                )
            if progresso:
                progresso(i + 1, total)


def publish_status(token, publish_id):
    """Consulta como esta o processamento do lado do TikTok."""
    data = _api(STATUS_URL, token, {"publish_id": publish_id})
    return {
        "status": data.get("status") or "",
        "fail_reason": data.get("fail_reason") or "",
        "uploaded_bytes": data.get("uploaded_bytes") or 0,
    }
