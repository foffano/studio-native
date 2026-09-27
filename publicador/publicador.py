"""Publicador do Studio Native para o Mac.

Publica no TikTok Shop os videos da fila do servidor, num navegador aberto
neste Mac -- com a internet de casa, que o TikTok aceita (o login a partir do
servidor e bloqueado). O roteiro e o mesmo do servidor (seller.py); este
arquivo so faz a ponte:

  1. conta ao servidor como esta (heartbeat) e recebe comandos da tela:
     abrir o navegador de uma loja, baixar produtos, responder a um pedido
     de ajuda;
  2. pega o proximo video da fila, baixa o arquivo e o poe na fila local;
  3. o seller.py publica, e o resultado volta para o servidor;
  4. o catalogo e as contas baixados aqui sobem para o servidor.

Os dados locais (login de cada loja, copia temporaria dos videos) ficam em
~/Library/Application Support/StudioNativePublicador/dados. O codigo vem do
servidor e se atualiza sozinho quando o servidor muda de versao.

Uso: python publicador.py            (roda)
     python publicador.py --configurar URL TOKEN
"""

import hashlib
import io
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

BASE = Path.home() / "Library" / "Application Support" / "StudioNativePublicador"
APP_DIR = Path(__file__).resolve().parent
DADOS = BASE / "dados"
VERSAO = "1"

sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BASE / "browsers"))
# Janela de verdade, na tela do Mac.
os.environ.setdefault("STUDIO_SELLER_HEADLESS", "0")
if Path("/Applications/Google Chrome.app").exists():
    os.environ.setdefault("STUDIO_SELLER_CHANNEL", "chrome")

import warnings  # noqa: E402

# O Python do sistema no macOS usa LibreSSL, e o urllib3 avisa disso a cada
# execucao. O aviso nao muda nada para o Publicador.
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import requests  # noqa: E402

import seller  # noqa: E402
import store  # noqa: E402

INTERVALO = 3  # segundos entre conversas com o servidor


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def avisar(titulo, texto):
    """Notificacao do macOS: o Publicador roda escondido atras de outras janelas."""
    try:
        script = f'display notification {_aspas(texto)} with title {_aspas(titulo)} sound name "Glass"'
        subprocess.run(["osascript", "-e", script], timeout=5, check=False)
    except Exception:  # noqa: BLE001
        pass


def _aspas(texto):
    return '"' + str(texto).replace("\\", "\\\\").replace('"', '\\"')[:200] + '"'


class Publicador:
    def __init__(self):
        self.url = store.setting_get("remote_url", "")
        self.token = store.setting_get("remote_token", "")
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        # pub_id -> ja passou por "enviando" aqui (para saber quando volta solto)
        self.meus = {}
        self.ultima_atencao = None
        self.ultimo_estado = ""
        self.fora_do_ar = False

    # -- conversa com o servidor --------------------------------------------

    def api(self, metodo, caminho, **kw):
        kw.setdefault("timeout", 30)
        r = self.http.request(metodo, self.url + caminho, **kw)
        if r.status_code == 401:
            raise SystemExit(
                "O servidor recusou o Publicador: o pareamento foi desfeito. "
                "Gere um novo comando em TikTok Shop › Publicar pelo Mac.")
        r.raise_for_status()
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else None

    def heartbeat(self):
        b = seller.BROWSER
        atual = dict(b.current) if b.current else None
        corpo = {
            "name": platform.node(),
            "version": VERSAO,
            "client_hash": _hash_instalado(),
            "current": atual,
            "attention": b.attention,
            "open_shop": b.shop if b.open else "",
            "logged_shops": [k for k in seller.shop_keys() if seller._session_configured(k)],
            "sync": b.sync if b.sync.get("shop") else None,
            "next_at": b.next_at if b.next_at > time.time() else 0,
        }
        return self.api("POST", "/api/worker/heartbeat", json=corpo)

    # -- um ciclo ------------------------------------------------------------

    def ciclo(self):
        hb = self.heartbeat()
        if self.fora_do_ar:
            log("Servidor de volta.")
            self.fora_do_ar = False

        if hb.get("client_hash") and hb["client_hash"] != _hash_instalado() and self.ocioso():
            self.atualizar(hb["client_hash"])

        seller.state_update(interval_min=hb.get("interval_min") or 3)
        self.espelhar_lojas(hb.get("shops") or [])
        for cmd in hb.get("commands") or []:
            self.executar(cmd)

        self.devolver_resultados()
        self.subir_catalogos()

        if hb.get("executor") == "mac" and not hb.get("paused") and self.pode_pegar():
            self.pegar()

        self.mostrar_estado()

    def espelhar_lojas(self, lojas):
        for l in lojas:
            if not l.get("key"):
                continue
            campos = {}
            if l.get("name"):
                campos["name"] = l["name"]
            if l.get("video_url") and not seller.shop_get(l["key"], "video_url"):
                campos["video_url"] = l["video_url"]
            if not seller.shop_exists(l["key"]) or campos:
                seller.shop_update(l["key"], **campos)
        # Loja removida no servidor: some daqui tambem (login incluso).
        chaves = {l["key"] for l in lojas}
        for k in seller.shop_keys():
            if k not in chaves and not store.shop_publications(states=("fila", "enviando")):
                try:
                    seller.remove_shop(k)
                    log(f"Loja {k} removida (foi removida no servidor).")
                except Exception as e:  # noqa: BLE001
                    log(f"Não consegui remover a loja {k}: {e}")

    def executar(self, cmd):
        tipo = cmd.get("type")
        loja = cmd.get("shop") or ""
        if tipo == "open_shop" and loja:
            if not seller.shop_exists(loja):
                seller.shop_update(loja)
            log(f"Abrindo o navegador em {seller.shop_name(loja)}. Entre na conta, se pedir.")
            seller.BROWSER.ensure_started(loja)
        elif tipo == "sync_shop" and loja:
            if not seller.shop_exists(loja):
                seller.shop_update(loja)
            log(f"Baixando produtos e contas de {seller.shop_name(loja)}...")
            seller.request_sync(loja)
        elif tipo == "answer":
            seller.reply(cmd.get("action") or "continuar")
        elif tipo == "close":
            threading.Thread(target=seller.close_browser, daemon=True).start()

    # -- a fila --------------------------------------------------------------

    def pendentes_locais(self):
        return store.shop_publications(states=("fila", "enviando"))

    def ocioso(self):
        return not self.pendentes_locais() and not seller.BROWSER.current

    def pode_pegar(self):
        b = seller.BROWSER
        return (self.ocioso() and not b.recording and not b.sync.get("running")
                and time.time() >= b.next_at)

    def pegar(self):
        trabalho = self.api("POST", "/api/worker/claim")
        if not trabalho or not trabalho.get("job"):
            return
        job = trabalho["job"]
        pub, out, loja = job["pub"], job["output"], job["shop"]
        log(f"Novo vídeo: {out.get('phrase') or out['file']} → @{pub['target'] or 'conta padrão'} "
            f"em {loja.get('name') or loja['key']}")
        destino = DADOS / "outputs" / out["file"]
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.http.get(f"{self.url}/api/worker/files/{out['id']}", stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(destino, "wb") as f:
                    for bloco in r.iter_content(1 << 20):
                        f.write(bloco)
        except Exception as e:  # noqa: BLE001
            destino.unlink(missing_ok=True)
            self.api("POST", f"/api/worker/jobs/{pub['id']}/result",
                     json={"state": "fila", "error": f"download falhou: {e}"})
            log(f"Não consegui baixar o vídeo ({e}); ele volta para a fila.")
            return

        if not seller.shop_exists(loja["key"]):
            seller.shop_update(loja["key"])
        if loja.get("name"):
            seller.shop_update(loja["key"], name=loja["name"])
        if loja.get("video_url") and not seller.shop_get(loja["key"], "video_url"):
            seller.shop_update(loja["key"], video_url=loja["video_url"])
        if not store.get_output(out["id"]):
            store.add_output(out["file"], library_id=out.get("library_id") or "", phrase=out.get("phrase") or "",
                             caption=out.get("caption") or "", hashtags=out.get("hashtags") or [],
                             output_id=out["id"])
        store.add_publication(
            output_id=out["id"], platform=seller.PLATFORM, mode="shop",
            product_ids=pub.get("product_ids") or [], target=pub.get("target") or "",
            shop=loja["key"], pub_id=pub["id"],
        )
        self.meus[pub["id"]] = False
        seller.state_update(paused=False)
        seller.BROWSER.next_at = 0
        seller.BROWSER.ensure_started(loja["key"])

    def devolver_resultados(self):
        for pub in store.shop_publications():
            pid = pub["id"]
            if pid not in self.meus and pub["state"] in ("fila", "enviando"):
                # Sobrou de uma execucao anterior do Publicador.
                self.meus[pid] = pub["state"] == "enviando"
            if pub["state"] == "enviando":
                self.meus[pid] = True
                continue
            if pub["state"] == "fila":
                if not self.meus.get(pid):
                    continue  # ainda nao comecou
                # Comecou e voltou para a fila: o navegador foi fechado antes de publicar.
                corpo = {"state": "fila", "pause": True}
                seller.state_update(paused=False)
            elif pub["state"] == "publicado":
                produto = (pub.get("product_ids") or [""])[0]
                p = store.get_shop_product(produto) if produto else None
                corpo = {
                    "state": "publicado",
                    "product_id": produto,
                    "product_title": (p or {}).get("name", ""),
                    "video_url": seller.shop_get(pub.get("shop") or "", "video_url"),
                    "accounts_seen": seller.shop_get(pub.get("shop") or "", "accounts"),
                }
            else:
                corpo = {"state": "erro", "error": pub.get("error") or "Falha no Publicador."}
            try:
                self.api("POST", f"/api/worker/jobs/{pid}/result", json=corpo)
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code != 404:
                    raise
            self.limpar(pub)
            rotulo = {"publicado": "Publicado", "fila": "Devolvido para a fila"}.get(corpo["state"], "Erro")
            log(f"{rotulo}: {corpo.get('error', '')}".rstrip(": "))
            if corpo["state"] == "publicado":
                avisar("Studio Native", "Vídeo publicado no TikTok Shop.")

    def limpar(self, pub):
        self.meus.pop(pub["id"], None)
        out = store.get_output(pub["output_id"])
        store.delete_publication(pub["id"])
        if out:
            (DADOS / "outputs" / out["file"]).unlink(missing_ok=True)
            store.delete_output(out["id"])

    def subir_catalogos(self):
        for loja in seller.shop_keys():
            quando = seller.shop_get(loja, "products_synced_at")
            if not quando or quando == store.setting_get(f"catalogo_enviado:{loja}", ""):
                continue
            info = seller.shop_get(loja, "account_info")
            corpo = {
                "seller": {"id": seller.shop_get(loja, "seller_id"), "name": seller.shop_get(loja, "name"),
                           "code": seller.shop_get(loja, "code")},
                "products": [
                    {k: p[k] for k in ("id", "name", "image_url", "price", "status")}
                    for p in store.list_shop_products(shop=loja)
                ],
                "accounts": [{"handle": h, **(info.get(h) or {})} for h in seller.shop_get(loja, "accounts")],
            }
            try:
                n = self.api("POST", f"/api/worker/shops/{loja}/catalog", json=corpo)
                log(f"Catálogo de {seller.shop_name(loja)} enviado ao servidor ({(n or {}).get('products', 0)} produtos).")
            except requests.HTTPError as e:
                msg = ""
                try:
                    msg = e.response.json().get("error", "")
                except Exception:  # noqa: BLE001
                    pass
                log(f"O servidor recusou o catálogo de {loja}: {msg or e}")
                avisar("Studio Native", msg or "O servidor recusou o catálogo.")
            store.setting_set(**{f"catalogo_enviado:{loja}": quando})

    # -- tela ---------------------------------------------------------------

    def mostrar_estado(self):
        b = seller.BROWSER
        atencao = b.attention
        if atencao and atencao != self.ultima_atencao:
            log(f"PRECISA DE VOCÊ: {atencao['message']}")
            avisar("Studio Native precisa de você", atencao["message"])
        self.ultima_atencao = atencao
        estado = (b.current or {}).get("step", "") if b.current else ""
        if estado and estado != self.ultimo_estado:
            log(f"  {estado}")
        self.ultimo_estado = estado

    # -- atualizacao do proprio codigo --------------------------------------

    def atualizar(self, esperado):
        try:
            r = self.http.get(f"{self.url}/api/worker/client.zip", timeout=60)
            r.raise_for_status()
            if hashlib.sha256(r.content).hexdigest()[:16] != esperado:
                return
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                z.extractall(APP_DIR)
            (BASE / "client.hash").write_text(esperado)
        except Exception as e:  # noqa: BLE001
            log(f"Atualização falhou ({e}); sigo com a versão atual.")
            return
        log("Publicador atualizado. Reiniciando...")
        seller.shutdown()
        time.sleep(2)
        os.execv(sys.executable, [sys.executable, str(APP_DIR / "publicador.py")])

    def rodar(self):
        log(f"Publicador do Studio Native conectado a {self.url}")
        log("Deixe esta janela aberta. Os vídeos da fila saem por um navegador neste Mac.")
        while True:
            try:
                self.ciclo()
            except SystemExit:
                raise
            except requests.RequestException as e:
                if not self.fora_do_ar:
                    log(f"Sem contato com o servidor ({e.__class__.__name__}). Tentando de novo...")
                self.fora_do_ar = True
            except Exception:  # noqa: BLE001
                log("Erro inesperado:\n" + traceback.format_exc())
            time.sleep(INTERVALO)


def _hash_instalado():
    try:
        return (BASE / "client.hash").read_text().strip()
    except OSError:
        return ""


def main():
    DADOS.mkdir(parents=True, exist_ok=True)
    (DADOS / "outputs").mkdir(exist_ok=True)
    store.init_store(DADOS / "studio.db")
    seller.init(store, DADOS, DADOS / "outputs")
    if len(sys.argv) >= 4 and sys.argv[1] == "--configurar":
        store.setting_set(remote_url=sys.argv[2].rstrip("/"), remote_token=sys.argv[3])
        print("Publicador configurado.")
        return
    if not store.setting_get("remote_url", "") or not store.setting_get("remote_token", ""):
        raise SystemExit("Publicador sem servidor configurado. Rode de novo o comando de instalação.")
    try:
        Publicador().rodar()
    except KeyboardInterrupt:
        log("Encerrando...")
        seller.shutdown()


if __name__ == "__main__":
    main()
