"""O Publicador do Mac: publicacao no TikTok Shop feita fora do servidor.

O login na Central do Vendedor a partir do servidor esbarra no TikTok (o IP e
de datacenter na Franca; a tela de login responde "acessando com muita
frequencia"). No Mac da pessoa, com a internet de casa, o mesmo roteiro
(seller.py) funciona. Entao o servidor continua sendo o painel -- videos,
fila, produtos, contas -- e o Mac so executa:

    Mac -> POST /api/worker/heartbeat   a cada poucos segundos: estado + comandos
    Mac -> POST /api/worker/claim       pega o proximo video da fila
    Mac -> GET  /api/worker/files/<id>  baixa o arquivo
    Mac -> POST /api/worker/jobs/<id>/result
    Mac -> POST /api/worker/shops/<loja>/catalog   produtos e contas baixados la

A autenticacao e um token proprio (nao a senha do app), gerado ao parear e
guardado aqui so como hash. O codigo do Publicador sai do proprio servidor
(client.zip), entao ele se atualiza junto com o app.
"""

import hashlib
import hmac
import io
import secrets
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import seller

# Sem sinal do Mac ha mais que isto, ele esta desligado (ou o Publicador fechado).
ONLINE_SECONDS = 45
# Um video pego pelo Mac que ficou orfao (Mac sumiu, ou ja esta em outro) vira
# erro depois disto -- nunca volta sozinho para a fila, para nao publicar duas vezes.
ORPHAN_SECONDS = 10 * 60

# O que vai no client.zip, relativo a raiz do app.
CLIENT_FILES = (
    "seller.py",
    "store.py",
    "captions.py",
    "cdp_viewer.py",
    "publicador/publicador.py",
    "publicador/requirements.txt",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Remote:
    def __init__(self):
        self.lock = threading.Lock()
        self.store = None
        self.base_dir = None
        self.last_seen = 0.0
        self.info = {}
        self.commands = []
        self._zip = None
        self._zip_hash = ""

    def init(self, store_module, base_dir):
        self.store = store_module
        self.base_dir = Path(base_dir)
        seller.REMOTE = self

    # -- pareamento ---------------------------------------------------------

    def pair(self):
        """Token novo (o anterior deixa de valer). Mostrado uma vez so."""
        token = secrets.token_urlsafe(32)
        self.store.setting_set(worker_token_hash=_hash(token), worker_paired_at=_now())
        return token

    def unpair(self):
        self.store.setting_set(worker_token_hash="", worker_paired_at="", executor="servidor")
        with self.lock:
            self.last_seen = 0.0
            self.info = {}
            self.commands = []

    def paired(self):
        return bool(self.store.setting_get("worker_token_hash", ""))

    def check(self, authorization):
        esperado = self.store.setting_get("worker_token_hash", "")
        if not esperado or not authorization or not authorization.startswith("Bearer "):
            return False
        return hmac.compare_digest(_hash(authorization[7:].strip()), esperado)

    # -- estado para a tela -------------------------------------------------

    def online(self):
        return time.monotonic() - self.last_seen < ONLINE_SECONDS

    def summary(self):
        if not self.paired():
            return {"paired": False, "online": False}
        return {
            "paired": True,
            "online": self.online(),
            "name": self.info.get("name", ""),
            "version": self.info.get("version", ""),
            "outdated": bool(self.info.get("client_hash")) and self.info.get("client_hash") != self.client_hash(),
            "seen_seconds_ago": int(time.monotonic() - self.last_seen) if self.last_seen else None,
            "paired_at": self.store.setting_get("worker_paired_at", ""),
        }

    def status(self):
        """O que seller.status() mostra quando quem publica e o Mac."""
        info = dict(self.info)
        if not self.online():
            return {
                "message": "O Mac está desligado ou com o Publicador fechado. A fila espera por ele.",
                "current": None,
                "attention": None,
                "open_shop": "",
                "logged_shops": info.get("logged_shops") or [],
                "sync": None,
            }
        atual = info.get("current")
        if info.get("attention"):
            mensagem = info["attention"]["message"]
        elif atual:
            mensagem = f"Publicando no Mac: {atual.get('step', '')}..."
        elif info.get("open_shop"):
            mensagem = f"Navegador aberto no Mac em “{seller.shop_name(info['open_shop'])}”."
        else:
            mensagem = "Publicador do Mac conectado."
        return {
            "message": mensagem,
            "current": atual,
            "attention": info.get("attention"),
            "open_shop": info.get("open_shop") or "",
            "logged_shops": info.get("logged_shops") or [],
            "sync": info.get("sync"),
            "next_at": info.get("next_at") or 0,
        }

    def send(self, comando):
        with self.lock:
            # O mesmo pedido duas vezes seguidas (dois cliques) vira um so.
            if self.commands and self.commands[-1] == comando:
                return
            self.commands = (self.commands + [comando])[-50:]

    # -- API do Mac ---------------------------------------------------------

    def heartbeat(self, payload):
        with self.lock:
            self.last_seen = time.monotonic()
            self.info = {
                "name": str(payload.get("name") or "")[:80],
                "version": str(payload.get("version") or "")[:40],
                "client_hash": str(payload.get("client_hash") or "")[:80],
                "current": payload.get("current"),
                "attention": payload.get("attention"),
                "open_shop": payload.get("open_shop") or "",
                "logged_shops": [k for k in (payload.get("logged_shops") or []) if isinstance(k, str)],
                "sync": payload.get("sync"),
                "next_at": payload.get("next_at") or 0,
            }
            comandos, self.commands = self.commands, []
        self._orfaos()
        return {
            "executor": seller.executor(),
            "paused": bool(seller.state_get("paused")),
            "interval_min": seller.state_get("interval_min"),
            "client_hash": self.client_hash(),
            "shops": [
                {"key": k, "name": seller.shop_get(k, "name"), "video_url": seller.shop_get(k, "video_url")}
                for k in seller.shop_keys()
            ],
            "commands": comandos,
        }

    def claim(self):
        """O proximo video da fila, ja marcado como do Mac."""
        if seller.executor() != "mac" or seller.state_get("paused"):
            return None
        with self.lock:
            for pub in self.store.shop_queue():
                output = self.store.get_output(pub["output_id"])
                caminho = self._arquivo(output)
                if not output or not caminho:
                    self.store.update_publication(
                        pub["id"], state="erro",
                        error="O arquivo do vídeo não está mais no servidor.")
                    continue
                loja = pub.get("shop") or ""
                self.store.update_publication(pub["id"], state="enviando", error="",
                                              worker="mac", claimed_at=_now())
                return {
                    "pub": {
                        "id": pub["id"],
                        "target": pub.get("target") or "",
                        "shop": loja,
                        "product_ids": pub.get("product_ids") or [],
                    },
                    "output": {
                        "id": output["id"],
                        "file": output["file"],
                        "size": caminho.stat().st_size,
                        "caption": output.get("caption") or "",
                        "phrase": output.get("phrase") or "",
                        "hashtags": output.get("hashtags") or [],
                        "library_id": output.get("library_id") or "",
                    },
                    "shop": {
                        "key": loja,
                        "name": seller.shop_get(loja, "name"),
                        "video_url": seller.shop_get(loja, "video_url"),
                    },
                }
        return None

    def file_for(self, output_id):
        pub_do_mac = any(
            p["output_id"] == output_id and p.get("worker") == "mac"
            for p in self.store.shop_publications(states=("enviando",))
        )
        if not pub_do_mac:
            return None
        return self._arquivo(self.store.get_output(output_id))

    def _arquivo(self, output):
        if not output:
            return None
        caminho = seller._output_dir / output["file"]
        return caminho if caminho.exists() else None

    def result(self, pub_id, data):
        pub = self.store.get_publication(pub_id)
        if not pub or pub.get("platform") != seller.PLATFORM or pub.get("worker") != "mac":
            raise LookupError("Publicação não encontrada.")
        if pub["state"] != "enviando":
            return pub  # ja resolvida (o Mac mandou o resultado duas vezes)
        estado = data.get("state")
        loja = pub.get("shop") or ""
        if data.get("video_url") and loja:
            seller.shop_update(loja, video_url=str(data["video_url"])[:500], last_login_ok=_now())
        if estado == "publicado":
            produto = str(data.get("product_id") or "")
            self.store.update_publication(
                pub_id, state="publicado", error="", published_at=_now(),
                **({"product_ids": [produto]} if produto else {}),
            )
            self.store.update_output(pub["output_id"], status="publicado")
            if produto and seller.PRODUCT_ID_RE.match(produto):
                seller.remember_product(loja, produto, str(data.get("product_title") or ""),
                                        self.store.get_output(pub["output_id"]))
            for handle in data.get("accounts_seen") or []:
                seller._remember_accounts(loja, [handle])
        elif estado == "fila":
            # O Mac soltou o video sem publicar (o navegador foi fechado antes).
            self.store.update_publication(pub_id, state="fila", error="", worker="", claimed_at="")
            if data.get("pause"):
                seller.state_update(paused=True)
        else:
            self.store.update_publication(
                pub_id, state="erro",
                error=str(data.get("error") or "Falha no Publicador do Mac.")[:500])
        return self.store.get_publication(pub_id)

    def catalog(self, loja, data):
        if not seller.shop_exists(loja):
            raise LookupError("Loja não encontrada.")
        vendedor = data.get("seller") or {}
        sid = str(vendedor.get("id") or "")
        if sid:
            for outra in seller.shop_keys():
                if outra != loja and seller.shop_get(outra, "seller_id") == sid:
                    raise ValueError(
                        f"Esta conta é da loja “{seller.shop_name(outra)}”, que já está cadastrada.")
        campos = {"products_synced_at": _now(), "last_login_ok": _now()}
        if sid:
            campos.update(seller_id=sid, name=str(vendedor.get("name") or "")[:200],
                          code=str(vendedor.get("code") or "")[:40])
        contas = [c for c in (data.get("accounts") or [])
                  if isinstance(c, dict) and seller.HANDLE_RE.match(c.get("handle") or "")]
        if contas:
            campos["accounts"] = [c["handle"] for c in contas]
            campos["account_info"] = {
                c["handle"]: {"id": str(c.get("id") or ""), "nickname": str(c.get("nickname") or ""),
                              "role": int(c.get("role") or 0), "eligible": c.get("eligible", True) is not False}
                for c in contas
            }
        produtos = [
            {"id": str(p["id"]), "name": str(p.get("name") or ""), "image_url": str(p.get("image_url") or ""),
             "price": str(p.get("price") or ""), "status": int(p.get("status") or 0)}
            for p in (data.get("products") or [])
            if isinstance(p, dict) and seller.PRODUCT_ID_RE.match(str(p.get("id") or ""))
        ]
        if data.get("products") is not None:
            self.store.save_shop_products(produtos, loja)
            threading.Thread(target=seller._baixar_miniaturas, args=(produtos,), daemon=True).start()
        seller.shop_update(loja, **campos)
        return len(produtos)

    def _orfaos(self):
        """Video marcado como do Mac que o Mac ja nao esta publicando."""
        atual = ((self.info.get("current") or {}).get("pub_id")) if self.online() else None
        agora = datetime.now(timezone.utc)
        for pub in self.store.shop_publications(states=("enviando",)):
            if pub.get("worker") != "mac" or pub["id"] == atual:
                continue
            try:
                idade = (agora - datetime.fromisoformat(pub.get("claimed_at") or "")).total_seconds()
            except ValueError:
                idade = ORPHAN_SECONDS + 1
            if idade > ORPHAN_SECONDS:
                self.store.update_publication(
                    pub["id"], state="erro",
                    error="O Mac parou no meio desta publicação. Confira no TikTok se o vídeo "
                          "saiu antes de tentar de novo.")

    # -- o codigo do Publicador ---------------------------------------------

    def client_zip(self):
        if self._zip is None:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for rel in CLIENT_FILES:
                    caminho = self.base_dir / rel
                    info = zipfile.ZipInfo(Path(rel).name, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, caminho.read_bytes())
            self._zip = buf.getvalue()
            self._zip_hash = hashlib.sha256(self._zip).hexdigest()[:16]
        return self._zip

    def client_hash(self):
        if self._zip is None:
            try:
                self.client_zip()
            except OSError:
                return ""
        return self._zip_hash


REMOTE = Remote()
