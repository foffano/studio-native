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

## Por que 43117 nao e a porta do backend

O backend sobe numa porta livre sorteada pelo Electron. Fixar ele em 43117
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
</style>
<div class="c"><h1 class="{cls}">{titulo}</h1><p>{texto}</p>
<p>Pode fechar esta aba e voltar ao Studio Native.</p></div>"""


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
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        erro = (params.get("error") or [""])[0]

        with _LOCK:
            fluxo = dict(_FLOW) if _FLOW else None

        if not fluxo:
            self._responder("Login expirado", "Tente conectar de novo pelo app.", "bad")
            return

        # O `state` e a defesa contra alguem induzir o navegador a completar um
        # login que nao foi o usuario que comecou.
        if not state or not secrets.compare_digest(state, fluxo["state_token"]):
            _set_flow(status="erro", error="O state nao confere; login descartado.")
            self._responder("Login recusado", "O state nao confere.", "bad")
            return

        if erro:
            _set_flow(status="erro", error=f"O TikTok recusou: {erro}")
            self._responder("Autorizacao negada", f"O TikTok respondeu: {erro}", "bad")
            return

        if not code:
            _set_flow(status="erro", error="O TikTok nao devolveu o code.")
            self._responder("Login incompleto", "Nenhum codigo recebido.", "bad")
            return

        try:
            tokens = _exchange(
                "/tiktok/token",
                {
                    "code": code,
                    "code_verifier": fluxo["verifier"],
                    "redirect_uri": REDIRECT_URI,
                },
                "Troca de token",
            )
            conta = _save_account(tokens)
        except TikTokError as e:
            _set_flow(status="erro", error=str(e))
            self._responder("Nao deu certo", str(e), "bad")
            return

        _set_flow(status="conectado", account_id=conta["id"], error="")
        self._responder(
            "Conta conectada",
            f"@{conta.get('nickname') or 'conta'} esta ligada ao Studio Native.",
            "ok",
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

def start_connect():
    """Prepara o login e devolve a URL de autorizacao para o app abrir."""
    global _FLOW, _SERVER, _THREAD

    config = service_config()

    _stop_flow()

    try:
        server = HTTPServer(("127.0.0.1", LOOPBACK_PORT), _CallbackHandler)
    except OSError as e:
        raise TikTokError(
            f"A porta {LOOPBACK_PORT} esta ocupada por outro programa, e o TikTok "
            f"exige exatamente ela no retorno do login. Feche o que estiver "
            f"usando a porta e tente de novo. ({e})"
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
        }
        _SERVER = server
        _THREAD = threading.Thread(
            target=_serve, args=(server, deadline), daemon=True
        )
        _THREAD.start()

    query = urllib.parse.urlencode({
        "client_key": config["client_key"],
        "scope": config.get("scopes") or "user.info.basic,video.upload",
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"url": f"{AUTHORIZE_URL}?{query}", "expira_em": FLOW_TIMEOUT}


def cancel_connect():
    _stop_flow()
    return {"state": "ocioso"}


def current_account():
    """Conta conectada, sem nenhum token dentro."""
    return store.public_account(store.active_account("tiktok"))


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
