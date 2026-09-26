"""Publicacao automatica no TikTok Shop pela Central do Vendedor.

O TikTok nao oferece API para postar video com produto (o carrinho laranja)
fora do programa de parceiros, entao este modulo faz o que a pessoa faria no
site: abre "Videos com produtos a venda", envia o arquivo, escolhe a conta,
vincula o produto, escreve a legenda e publica -- um video por vez, com
intervalo entre eles.

Tres pecas, no mesmo desenho do eco-native:

* **O navegador** (``SellerBrowser``): um Chromium com perfil proprio em
  ``data/seller_browser``, onde fica o login. Uma thread so e dona dele -- o
  Playwright sincrono nao pode ser usado de outra -- e e nela que a automacao
  roda.
* **O visor** (``_Viewer``): outra thread, presa ao mesmo navegador por uma
  conexao crua do DevTools (``cdp_viewer``). Tira foto da aba e repassa clique
  e teclado de quem esta olhando. E por ele que o login e feito e que a pessoa
  resolve a verificacao anti-robo quando o TikTok pede -- o servidor nao tem
  tela.
* **A fila**: linhas em ``publications`` com ``platform='tiktok_shop'``. Ficam
  no SQLite, entao sobrevivem a um reinicio e aparecem no card do video como
  qualquer outra publicacao.

Quando um passo nao sai sozinho (o site mudou, apareceu uma verificacao, a
busca achou dois produtos parecidos), a automacao nao desiste: ela para, avisa
o que falta, e espera a pessoa fazer aquele passo no visor. Depois segue.
"""

import json
import os
import queue
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from cdp_viewer import CdpBrowser, CdpError

SELLER_ORIGIN = os.getenv("STUDIO_SELLER_URL", "https://seller-br.tiktok.com").rstrip("/")
SELLER_HOME = SELLER_ORIGIN + "/homepage"
# "LIVE e video" > "Videos com produtos a venda", visto numa sessao gravada em
# 2026-09-26. Se o TikTok mudar o endereco, o roteiro volta pelo menu e guarda
# o novo no banco (tabela shops).
SELLER_VIDEOS = SELLER_ORIGIN + "/shoppable-videos/create-content/live-highlight"

WIDTH, HEIGHT = 1280, 800
PLATFORM = "tiktok_shop"

# Quanto tempo o navegador fica aberto sem fila e sem ninguem olhando.
IDLE_CLOSE_SECONDS = 15 * 60
# O visor para de tirar foto quando ninguem pede quadro ha este tempo.
VIEWER_IDLE_SECONDS = 60
FRAME_INTERVAL = 0.45
# Quanto a automacao espera a pessoa resolver algo antes de desistir do video.
ATTENTION_TIMEOUT = 30 * 60
# Tres videos seguidos com erro pausam a fila: algo mudou e repetir so gasta
# tentativa (e chama a atencao do anti-robo).
MAX_FALHAS_SEGUIDAS = 3

# O estado mora no SQLite do app (store.py): tabelas shops e shop_accounts, e
# os ajustes soltos em app_settings. Ate a versao de uma loja so era um
# seller_state.json; init() o importa uma vez e o aposenta.
DEFAULT_SETTINGS = {
    # A loja cujo perfil o navegador abre quando nada pede outra.
    "active_shop": "",
    # "loja/@conta" da ultima publicacao, para o dialogo ja vir marcado.
    "last_account": "",
    "interval_min": 3,
    "paused": False,
}

# ---------------------------------------------------------------------------
# configuracao e estado salvo
# ---------------------------------------------------------------------------

_store = None
_output_dir = None
_data_dir = None
_state_lock = threading.Lock()


def _profiles_root():
    return _data_dir / "seller_browser"


def _profile_dir(shop):
    return _profiles_root() / shop


def _debug_dir():
    return _data_dir / "seller_debug"


def _importar_json_antigo():
    """seller_state.json -> SQLite, uma vez. Serve aos dois formatos que ele
    teve: o de uma loja so (campos soltos) e o de varias ("shops")."""
    arquivo = _data_dir / "seller_state.json"
    raiz = _profiles_root()
    try:
        antigo = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        antigo = {}

    lojas = dict(antigo.get("shops") or {})
    perfil_solto = (raiz / "Default").exists() or (raiz / "Local State").exists()
    campos_soltos = ("video_url", "accounts", "account_info", "products_synced_at", "last_login_ok")
    if perfil_solto or any(antigo.get(k) for k in campos_soltos):
        # Uma loja so: o perfil era a propria pasta seller_browser/. Mover para
        # a subpasta da loja preserva o login.
        chave = "loja-1"
        while chave in lojas or _store.get_shop(chave):
            chave = new_shop_key()
        if perfil_solto:
            destino = raiz / chave
            destino.mkdir(parents=True, exist_ok=True)
            for item in list(raiz.iterdir()):
                if item.name != chave and not (item.is_dir() and item.name.startswith("loja-")):
                    os.replace(item, destino / item.name)
        lojas[chave] = {k: antigo.get(k) for k in campos_soltos}
        if antigo.get("last_account") and "/" not in antigo["last_account"]:
            antigo["last_account"] = f"{chave}/{antigo['last_account']}"
        antigo.setdefault("active_shop", chave)
        _store.assign_shop_to_orphans(chave)

    for chave, loja in lojas.items():
        _store.upsert_shop(chave, **{k: loja.get(k) or "" for k in _store.SHOP_FIELDS
                                     if k != "created_at" and loja.get(k)},
                           created_at=loja.get("created_at") or _now())
        info = loja.get("account_info") or {}
        _store.set_shop_accounts(chave, [
            {"handle": h, **(info.get(h) or {})} for h in (loja.get("accounts") or [])
            if HANDLE_RE.match(h or "")
        ])
    ajustes = {k: antigo[k] for k in DEFAULT_SETTINGS if k in antigo}
    if ajustes:
        _store.setting_set(**ajustes)
    if arquivo.exists():
        os.replace(arquivo, arquivo.with_suffix(".json.importado"))


def state_get(key):
    return _store.setting_get(key, DEFAULT_SETTINGS.get(key))


def state_update(**fields):
    _store.setting_set(**fields)


SHOP_KEY_RE = re.compile(r"^loja-[a-z0-9]{1,12}$")


def new_shop_key():
    return "loja-" + os.urandom(3).hex()


def shop_get(shop, field):
    """Um campo da loja. "accounts" e "account_info" vem de shop_accounts."""
    if field in ("accounts", "account_info"):
        contas = _store.list_shop_accounts(shop) if shop else []
        if field == "accounts":
            return [c["handle"] for c in contas]
        return {c["handle"]: {"id": c["tt_id"], "nickname": c["nickname"],
                              "role": c["role"], "eligible": c["eligible"]} for c in contas}
    loja = _store.get_shop(shop) if shop else None
    return (loja or {}).get(field) or ""


def shop_update(shop, **fields):
    with _state_lock:
        contas = fields.pop("accounts", None)
        info = fields.pop("account_info", None)
        _store.upsert_shop(shop, **fields)
        if contas is not None or info is not None:
            if contas is None:
                contas = shop_get(shop, "accounts")
            if info is None:
                info = shop_get(shop, "account_info")
            _store.set_shop_accounts(shop, [{"handle": h, **(info.get(h) or {})} for h in contas])


def shop_exists(shop):
    return bool(shop and _store.get_shop(shop))


def shop_keys():
    return [l["key"] for l in _store.list_shops()] if _store else []


def shop_name(shop):
    return shop_get(shop, "name") or "Loja nova"


def _remember_accounts(shop, handles):
    handles = [h for h in handles if HANDLE_RE.match(h or "")]
    if not handles or not shop:
        return
    atuais = shop_get(shop, "accounts") or []
    novos = [h for h in handles if h not in atuais]
    if novos:
        shop_update(shop, accounts=(atuais + novos)[:30])


def accounts_view(shop=None):
    """As contas para a tela, loja por loja; as baixadas da Central primeiro."""
    contas = []
    for loja in [shop] if shop else shop_keys():
        nome = shop_name(loja)
        for c in _store.list_shop_accounts(loja):
            contas.append({
                "shop": loja,
                "shop_name": nome,
                "handle": c["handle"],
                "nickname": c["nickname"],
                "role": c["role"],
                "eligible": c["eligible"],
                # A foto vem do CDN do TikTok, que hoje recusa (403) ate na
                # propria Central. Sem arquivo, a tela mostra a inicial.
                "avatar": avatar_path(c["handle"]) is not None,
            })
    return contas


def shop_of_account(handle):
    """A loja de uma conta; None se ela aparece em mais de uma (ou nenhuma)."""
    donas = [k for k in shop_keys() if handle in (shop_get(k, "accounts") or [])]
    return donas[0] if len(donas) == 1 else None


def avatar_path(handle):
    if not HANDLE_RE.match(handle or ""):
        return None
    caminho = _thumbs_dir() / f"conta-{handle}.jpg"
    return caminho if caminho.exists() else None


def remember_product(shop, product_id, title="", output=None):
    """Produto usado numa publicacao: entra no catalogo da loja e, se o video
    ainda nao tinha produto nela, fica vinculado para a proxima vez."""
    if not product_id or not shop:
        return
    _store.upsert_shop_product(product_id, title, shop)
    if output and not _store.product_for_output(output, shop):
        if output.get("library_id"):
            _store.set_product_link("library", output["library_id"], shop, product_id)
        else:
            _store.set_product_link("output", output["id"], shop, product_id)


# ---------------------------------------------------------------------------
# catalogo de produtos
# ---------------------------------------------------------------------------
# A lista vem da mesma API que a pagina "Produtos" da Central usa, chamada de
# dentro da pagina ja logada (os cookies vao junto). Vista numa sessao gravada
# em 2026-09-26: GET /api/v1/product/local/products/list, 50 por pagina.

SYNC_EVERY_SECONDS = 12 * 3600

JS_PRODUTOS = r"""
async (pagina) => {
  const u = new URL('/api/v1/product/local/products/list', location.origin);
  const p = {tab_id: 2, page_number: pagina, page_size: 50, sku_number: 1,
             product_sort_fields: 3, product_sort_types: 0, locale: 'pt-BR', language: 'pt'};
  for (const [k, v] of Object.entries(p)) u.searchParams.set(k, v);
  // O SDK de seguranca do TikTok (webmssdk) embrulha o fetch da pagina e
  // quebra com um objeto URL: vai texto. Se ainda assim falhar, XHR.
  let j = null, http = 0;
  try {
    const r = await fetch(u.toString(), {credentials: 'include'});
    http = r.status;
    j = await r.json();
  } catch (_) {
    j = await new Promise((ok) => {
      const x = new XMLHttpRequest();
      x.open('GET', u.toString());
      x.withCredentials = true;
      x.onload = () => { http = x.status; try { ok(JSON.parse(x.responseText)); } catch (_) { ok(null); } };
      x.onerror = () => ok(null);
      x.send();
    });
  }
  if (!j) return {erro: `HTTP ${http}`};
  if (j.code !== 0) return {erro: j.message || `código ${j.code}`};
  const d = j.data || {};
  return {
    total: d.total_product_count || 0,
    produtos: (d.products || []).map((x) => ({
      id: String(x.product_id),
      name: x.product_name || '',
      image_url: ((x.image && (x.image.thumb_url_list || x.image.url_list)) || [])[0] || '',
      price: ((x.sale_price_ranges || [])[0] || {}).price_range || x.price_range || '',
      status: x.product_status || 0,
    })),
  };
}
"""


# As contas vinculadas (oficial e de marketing) vem da mesma API que a gaveta
# de envio usa para montar "Contas de publicacao". Vista em 2026-09-26.
JS_CONTAS = r"""
async () => {
  const u = new URL('/api/v1/seller/video_center/ai/local_sellers/list', location.origin);
  u.searchParams.set('locale', 'pt-BR');
  u.searchParams.set('language', 'pt');
  let j = null;
  try { j = await (await fetch(u.toString(), {credentials: 'include'})).json(); } catch (_) {}
  if (!j || j.code !== 0) return {erro: (j && j.message) || 'sem resposta'};
  const contas = [];
  const primeira = ((j.data && j.data.sellers) || [])[0] || {};
  const seller = {id: String(primeira.seller_id || ''), name: primeira.seller_name || '', code: primeira.seller_code || ''};
  for (const loja of (j.data && j.data.sellers) || []) {
    for (const c of loja.binded_creators || []) {
      contas.push({
        id: String(c.id || ''), handle: c.name || '', nickname: c.nick_name || '',
        role: c.role || 0, eligible: c.post_eligibility !== 0,
        avatar_url: ((c.avatar && c.avatar.thumb_url_list) || [])[0] || '',
      });
    }
  }
  return {contas, seller};
}
"""


def _thumbs_dir():
    return _data_dir / "shop_thumbs"


def thumb_path(product_id):
    if not PRODUCT_ID_RE.match(str(product_id)):
        return None
    caminho = _thumbs_dir() / f"{product_id}.jpg"
    return caminho if caminho.exists() else None


def _baixar_miniaturas(produtos):
    """As URLs de imagem do TikTok sao assinadas e vencem; a copia local nao."""
    import requests

    pasta = _thumbs_dir()
    pasta.mkdir(parents=True, exist_ok=True)
    for p in produtos:
        destino = pasta / f"{p['id']}.jpg"
        if destino.exists() or not p.get("image_url"):
            continue
        try:
            r = requests.get(p["image_url"], timeout=15)
            if r.ok and r.content:
                destino.write_bytes(r.content)
        except Exception:  # noqa: BLE001 -- miniatura e enfeite
            pass


def _now():
    return datetime.now(timezone.utc).isoformat()


HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{2,40}$")
PRODUCT_ID_RE = re.compile(r"^\d{12,22}$")


def playwright_available():
    try:
        import playwright.sync_api  # noqa: F401
        return True, ""
    except ImportError:
        return False, (
            "O Playwright nao esta instalado neste servidor. Rode "
            "`pip install -r requirements.txt` e `python -m playwright install "
            "--with-deps chromium`."
        )


# ---------------------------------------------------------------------------
# excecoes do fluxo
# ---------------------------------------------------------------------------

class StepError(Exception):
    """Um passo nao aconteceu. A mensagem vai para a tela."""


class Skip(Exception):
    """A pessoa mandou pular este video."""


class MarkedDone(Exception):
    """A pessoa confirmou que o video ja saiu."""


class Abort(Exception):
    """O navegador esta sendo fechado."""


# ---------------------------------------------------------------------------
# JavaScript que roda na pagina
# ---------------------------------------------------------------------------
# Nada de classe CSS: as da Central do Vendedor sao geradas e mudam a cada
# versao do site. Tudo e achado pelo texto que a pessoa ve -- o mesmo que ela
# usaria para achar o botao -- e clicado pelo mouse, nas coordenadas.

JS_HELPERS = r"""
const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
const shown = (el) => {
  if (!el || !el.getBoundingClientRect) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return false;
  for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
    const s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
  }
  return true;
};
const byText = (t, opts = {}) => {
  const alvo = norm(t);
  const root = opts.root || document.body;
  const out = [];
  for (const el of root.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'svg', 'path'].includes(el.tagName)) continue;
    const bruto = norm(el.textContent);
    if (!bruto.includes(alvo)) continue;
    if (!shown(el)) continue;
    const txt = norm(el.innerText);
    if (opts.contains ? txt.includes(alvo) : txt === alvo) out.push(el);
  }
  // Fica so o mais fundo de cada ramo: o <span> do botao, nao a pagina inteira.
  return out.filter((el) => !out.some((o) => o !== el && el.contains(o)));
};
// Texto que quebra em duas linhas tem o centro do retangulo no vazio entre
// elas; o primeiro pedaco de linha e sempre clicavel.
const rectOf = (el) => {
  const partes = el.getClientRects();
  return partes.length > 1 ? partes[0] : el.getBoundingClientRect();
};
const onTop = (el) => {
  const r = rectOf(el);
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
  const hit = document.elementFromPoint(x, y);
  return !!hit && (hit === el || el.contains(hit) || hit.contains(el));
};
const box = (el) => {
  el.scrollIntoView({ block: 'center', inline: 'nearest' });
  const r = rectOf(el);
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height, top: onTop(el) };
};
const clickableBox = (els) => {
  for (const el of els) {
    const b = box(el);
    if (b.top) return b;
  }
  return null;
};
const asButton = (el) => el.closest('button, [role="button"], a') || el;
const disabled = (el) => {
  const b = asButton(el);
  return !!(b.disabled || b.getAttribute('aria-disabled') === 'true' || /disabled/i.test(b.className || ''));
};
// O campo de um rotulo: o primeiro que vem depois dele na pagina, subindo aos
// poucos. Pegar o primeiro do bloco confundiria Descricao e Hashtags quando os
// dois moram no mesmo bloco.
const fieldNear = (label) => {
  const sel = 'textarea, [contenteditable="true"], input[type="text"], input:not([type])';
  for (let e = label, i = 0; e && i < 6; e = e.parentElement, i++) {
    const f = Array.from(e.querySelectorAll(sel)).find((x) =>
      shown(x) && (label.compareDocumentPosition(x) & Node.DOCUMENT_POSITION_FOLLOWING));
    if (f) return f;
  }
  return null;
};
const fieldValue = (f) => f ? norm(f.value !== undefined ? f.value : f.innerText) : '';
const CAPTCHA = [
  '#captcha_container', '#captcha-verify-container-main-page', '.captcha_verify_container',
  '.captcha-verify-container', '[class*="captcha_verify"]', '[class*="secsdk-captcha"]',
  '[id*="secsdk-captcha"]', 'iframe[src*="captcha"]', 'iframe[src*="verifycenter"]',
];
const hasCaptcha = () => CAPTCHA.some((s) => Array.from(document.querySelectorAll(s)).some(shown));
"""


# Gravador: cada clique na pagina vira uma descricao do elemento clicado (texto,
# classes, papel, a cadeia de pais). Nada do que se digita e gravado -- so que
# houve digitacao, e em qual campo -- para uma senha nunca parar num arquivo.
RECORDER_JS = r"""
(() => {
  if (window.__snRecInstalled) return;
  window.__snRecInstalled = true;
  const txt = (el) => ((el && el.innerText) || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const desc = (el) => el && el.nodeType === 1 ? {
    tag: el.tagName.toLowerCase(), id: el.id || '', cls: String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').slice(0, 200),
    role: el.getAttribute('role') || '', type: el.getAttribute('type') || '',
    placeholder: el.getAttribute('placeholder') || '', aria: el.getAttribute('aria-label') || '',
    accept: el.getAttribute('accept') || '', text: txt(el),
  } : null;
  const cadeia = (el) => { const out = []; for (let e = el, i = 0; e && e.nodeType === 1 && i < 8; e = e.parentElement, i++) out.push(desc(e)); return out; };
  const rect = (el) => { const r = el.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; };
  const enviar = (tipo, el, extra) => {
    try { window.__snRecord({tipo, url: location.href, alvo: desc(el), pais: cadeia(el).slice(1), rect: rect(el), ...extra}); } catch (_) {}
  };
  document.addEventListener('click', (e) => enviar('clique', e.target, {x: e.clientX, y: e.clientY}), true);
  document.addEventListener('change', (e) => {
    const el = e.target;
    const arquivos = el.files ? Array.from(el.files).map((f) => f.name) : undefined;
    enviar('mudanca', el, {arquivos});
  }, true);
  let ultimo = null;
  document.addEventListener('input', (e) => {
    if (ultimo === e.target) return;  // um registro por campo, nao por tecla
    ultimo = e.target;
    enviar('digitacao', e.target, {senha: e.target.type === 'password'});
  }, true);
})();
"""


# ---------------------------------------------------------------------------
# o navegador
# ---------------------------------------------------------------------------

def _headless():
    """Com tela (ou Xvfb) o Chromium roda de verdade; sem, cai no headless.

    Headless o anti-robo do TikTok desconfia mais -- por isso a imagem Docker
    roda o app dentro do xvfb-run.
    """
    forcado = os.getenv("STUDIO_SELLER_HEADLESS", "").strip()
    if forcado in ("0", "1"):
        return forcado == "1"
    if sys.platform in ("win32", "darwin"):
        return False
    return not os.getenv("DISPLAY")


def _devtools_endpoint(port_file, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            port = port_file.read_text(encoding="utf-8").split()[0]
            if port.isdigit():
                return f"http://127.0.0.1:{port}"
        except (OSError, IndexError):
            pass
        time.sleep(0.1)
    return None


class SellerBrowser:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._viewer = None
        self.endpoint = None
        self.open = False
        self.starting = False
        self.error = ""
        self.stop_requested = False
        self.last_activity = time.monotonic()
        self.current = None          # {"pub_id", "output_id", "step", "phrase"}
        self.attention = None        # {"message", "kind"}
        self.replies = queue.Queue()
        self.next_at = 0.0
        self.falhas_seguidas = 0
        self.page_url = ""
        # Modo gravacao: {"dir": Path, "n": int, "pendentes": [(quando, evento)]}
        self.recording = None
        self._snapshot_pedido = False
        # Loja pedida para a sincronizacao (chave), ou "".
        self.sync_pedido = ""
        self.sync = {"running": False, "error": "", "count": 0, "shop": ""}
        # A loja cujo perfil esta aberto, e a que alguem pediu. Diferentes, o
        # navegador fecha e abre de novo com o perfil pedido.
        self.shop = ""
        self.want_shop = ""

    # -- ciclo de vida ------------------------------------------------------

    def alive(self):
        return bool(self._thread and self._thread.is_alive())

    def ensure_started(self, shop=None):
        with self._lock:
            self.last_activity = time.monotonic()
            if shop:
                self.want_shop = shop
            if self.alive():
                # Aberto com outra loja: o _loop percebe e troca de perfil.
                return
            ok, hint = playwright_available()
            if not ok:
                self.error = hint
                return
            self.stop_requested = False
            self.error = ""
            self.starting = True
            self._thread = threading.Thread(target=self._run, name="tiktok-seller-browser", daemon=True)
            self._thread.start()

    def request_close(self):
        self.stop_requested = True
        self.replies.put("abort")

    def touch(self):
        self.last_activity = time.monotonic()

    def _check_abort(self):
        if self.stop_requested:
            raise Abort()

    def _run(self):
        motivo = "erro"
        try:
            from playwright.sync_api import sync_playwright

            loja = self.want_shop or state_get("active_shop") or (shop_keys() or [""])[0]
            if not loja:
                raise RuntimeError("Nenhuma loja cadastrada.")
            if not shop_exists(loja):
                shop_update(loja, created_at=_now())
            self.shop = self.want_shop = loja
            state_update(active_shop=loja)
            perfil = _profile_dir(loja)
            perfil.mkdir(parents=True, exist_ok=True)
            port_file = perfil / "DevToolsActivePort"
            port_file.unlink(missing_ok=True)
            # Perfil travado por um Chromium que morreu sem fechar.
            for trava in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                try:
                    (perfil / trava).unlink()
                except OSError:
                    pass

            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=str(perfil),
                    headless=_headless(),
                    viewport={"width": WIDTH, "height": HEIGHT},
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                    ignore_default_args=["--enable-automation"],
                    chromium_sandbox=os.getenv("STUDIO_CHROMIUM_SANDBOX", "0") == "1",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        # O visor se conecta por aqui. So escuta no loopback.
                        "--remote-debugging-port=0",
                        "--disable-dev-shm-usage",
                        "--no-first-run",
                        "--lang=pt-BR",
                        f"--window-size={WIDTH},{HEIGHT + 90}",
                    ],
                )
                try:
                    self.endpoint = _devtools_endpoint(port_file)
                    context.expose_binding("__snRecord", self._on_record)
                    context.add_init_script(RECORDER_JS)
                    context.on("page", lambda p: p.on("filechooser", self._on_file_chooser))
                    for p in context.pages:
                        p.on("filechooser", self._on_file_chooser)
                    page = self._work_page(context)
                    self.open = True
                    self.starting = False
                    try:
                        page.goto(shop_get(loja, "video_url") or SELLER_VIDEOS,
                                  wait_until="domcontentloaded", timeout=60_000)
                    except Exception as e:  # noqa: BLE001
                        self.error = f"Nao abriu a Central do Vendedor: {e}"
                    motivo = self._loop(context)
                finally:
                    self.open = False
                    self._stop_viewer()
                    try:
                        context.close()
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as e:  # noqa: BLE001
            self.error = f"Falha no navegador: {e}"
        finally:
            self.open = False
            self.starting = False
            self.endpoint = None
            self.current = None
            self.attention = None
            # Troca de loja, ou fechou por ociosidade mas chegou trabalho no
            # meio: sobe de novo (com o perfil de self.want_shop).
            if motivo == "trocar" or (motivo == "ocioso" and _has_work() and not self.stop_requested):
                threading.Timer(1.5, self.ensure_started).start()

    def _work_page(self, context):
        for p in context.pages:
            if not p.is_closed():
                return p
        return context.new_page()

    def _loop(self, context):
        while not self.stop_requested:
            page = self._work_page(context)
            self.page_url = page.url
            self._drenar_gravacao(context)
            if self.want_shop and self.want_shop != self.shop and not self.recording:
                return "trocar"
            if self.sync_pedido and self.sync_pedido != self.shop:
                self.want_shop = self.sync_pedido
                return "trocar"
            if self._precisa_sincronizar(page):
                self._sincronizar_produtos(page)
                continue
            pub = self._next_job()
            if pub:
                loja = pub.get("shop") or self.shop
                if loja != self.shop:
                    # O proximo video e de outra loja: fecha e abre o perfil dela.
                    self.want_shop = loja
                    return "trocar"
                self._processar(page, pub)
                self.touch()
                continue
            ocioso = time.monotonic() - self.last_activity > IDLE_CLOSE_SECONDS
            olhando = self._viewer and self._viewer.watched()
            if ocioso and not olhando and not self._waiting_next():
                return "ocioso"
            # Espera com o Playwright bombeando eventos (abas novas, fechadas).
            try:
                page.wait_for_timeout(300 if self.recording else 1000)
            except Exception:  # noqa: BLE001 -- a aba fechou; a proxima volta abre outra
                time.sleep(0.5)
        return "fechado"

    def _precisa_sincronizar(self, page):
        if self.recording or self.current:
            return False
        if self.sync_pedido:
            return True
        # Automatico: logado e com o catalogo velho (ou nunca baixado).
        url = (page.url or "").lower()
        logado = url.startswith(SELLER_ORIGIN.lower()) and not any(
            p in url for p in ("/account/login", "/login", "/passport", "/register"))
        if not logado:
            return False
        ultimo = shop_get(self.shop, "products_synced_at") or ""
        try:
            idade = time.time() - datetime.fromisoformat(ultimo).timestamp()
        except ValueError:
            idade = float("inf")
        erro_desta = self.sync.get("error") and self.sync.get("shop") == self.shop
        return idade > SYNC_EVERY_SECONDS and not erro_desta

    def _sincronizar_produtos(self, page):
        loja = self.shop
        self.sync_pedido = ""
        self.sync = {"running": True, "error": "", "count": 0, "shop": loja}
        try:
            if not (page.url or "").startswith(SELLER_ORIGIN):
                page.goto(shop_get(loja, "video_url") or SELLER_VIDEOS, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2000)
            url = (page.url or "").lower()
            if any(p in url for p in ("/account/login", "/login", "/passport")):
                raise StepError("Entre na conta TikTok Seller antes de baixar os produtos.")
            # Primeiro: qual loja e esta. A mesma loja cadastrada duas vezes
            # dividiria o catalogo em dois.
            self._identificar_loja(page, loja)
            produtos, pagina = [], 1
            while pagina <= 60:
                r = page.evaluate(JS_PRODUTOS, pagina)
                if r.get("erro"):
                    raise StepError(f"A Central recusou a lista de produtos: {r['erro']}")
                produtos += r["produtos"]
                self.sync["count"] = len(produtos)
                if not r["produtos"] or len(produtos) >= r["total"]:
                    break
                pagina += 1
                page.wait_for_timeout(random.uniform(600, 1200))
            _store.save_shop_products(produtos, loja)
            self._sincronizar_contas(page, loja)
            shop_update(loja, products_synced_at=_now(), last_login_ok=_now())
            threading.Thread(target=_baixar_miniaturas, args=(produtos,), daemon=True).start()
            self.sync = {"running": False, "error": "", "count": len(produtos), "shop": loja}
        except Exception as e:  # noqa: BLE001
            self.sync = {"running": False, "error": str(e)[:300], "count": 0, "shop": loja}
            print(f"[seller] sincronizacao de produtos falhou: {e}", flush=True)

    def _identificar_loja(self, page, loja):
        try:
            r = page.evaluate(JS_CONTAS)
        except Exception as e:  # noqa: BLE001
            print(f"[seller] identificacao da loja falhou: {e}", flush=True)
            return
        vendedor = r.get("seller") or {}
        sid = vendedor.get("id") or ""
        if not sid:
            return
        for outra in shop_keys():
            if outra != loja and shop_get(outra, "seller_id") == sid:
                raise StepError(
                    f"Esta conta é da loja “{shop_name(outra)}”, que já está cadastrada. "
                    "Remova esta loja nova e use aquela."
                )
        shop_update(loja, seller_id=sid, name=vendedor.get("name") or shop_name(loja),
                    code=vendedor.get("code") or "")

    def _sincronizar_contas(self, page, loja):
        """Melhor-esforco: sem isto as contas ainda aparecem ao publicar."""
        try:
            r = page.evaluate(JS_CONTAS)
        except Exception as e:  # noqa: BLE001
            print(f"[seller] lista de contas falhou: {e}", flush=True)
            return
        contas = [c for c in (r.get("contas") or []) if HANDLE_RE.match(c.get("handle") or "")]
        if not contas:
            return
        info = dict(shop_get(loja, "account_info") or {})
        for c in contas:
            info[c["handle"]] = {k: c[k] for k in ("id", "nickname", "role", "eligible")}
        # Oficial primeiro, depois as de marketing; as que so apareciam no
        # historico ficam no fim.
        ordem = [c["handle"] for c in sorted(contas, key=lambda c: c["role"] or 9)]
        antigas = [h for h in (shop_get(loja, "accounts") or []) if h not in ordem]
        shop_update(loja, accounts=ordem + antigas, account_info=info)

        def baixar():
            import requests
            _thumbs_dir().mkdir(parents=True, exist_ok=True)
            for c in contas:
                if not c.get("avatar_url"):
                    continue
                try:
                    resp = requests.get(c["avatar_url"], timeout=15)
                    if resp.ok and resp.content:
                        (_thumbs_dir() / f"conta-{c['handle']}.jpg").write_bytes(resp.content)
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=baixar, daemon=True).start()

    def _waiting_next(self):
        return _has_work() and time.time() < self.next_at

    def _next_job(self):
        # Gravando, o navegador e da pessoa: a fila espera.
        if self.recording or state_get("paused") or time.time() < self.next_at:
            return None
        fila = _store.shop_queue()
        return fila[0] if fila else None

    # -- um video -----------------------------------------------------------

    def _processar(self, page, pub):
        output = _store.get_output(pub["output_id"])
        pub_id = pub["id"]
        if not output:
            _store.update_publication(pub_id, state="erro", error="O vídeo não existe mais no catálogo.")
            return
        caminho = _output_dir / output["file"]
        if not caminho.exists():
            _store.update_publication(pub_id, state="erro", error="O arquivo do vídeo não está mais no disco.")
            return

        _store.update_publication(pub_id, state="enviando", error="")
        self.current = {
            "pub_id": pub_id,
            "output_id": output["id"],
            "phrase": output.get("phrase") or output.get("caption") or "",
            "step": "Abrindo a Central do Vendedor",
        }
        self.replies = queue.Queue()
        job = _Publicacao(self, page, pub, output, caminho)
        try:
            produto = job.run()
            _store.update_publication(
                pub_id, state="publicado", error="", published_at=_now(),
                product_ids=[produto] if produto else [],
            )
            _store.update_output(output["id"], status="publicado")
            self.falhas_seguidas = 0
        except MarkedDone:
            _store.update_publication(pub_id, state="publicado", error="", published_at=_now())
            _store.update_output(output["id"], status="publicado")
            self.falhas_seguidas = 0
        except Skip:
            _store.update_publication(pub_id, state="erro", error="Pulado por você.")
        except Abort:
            if job.clicou_publicar:
                _store.update_publication(
                    pub_id, state="erro",
                    error="O navegador fechou logo depois de clicar em Publicar. "
                          "Confira no TikTok se o vídeo saiu antes de tentar de novo.",
                )
            else:
                # Nada foi publicado: volta para a fila, e a fila pausa para
                # nao reabrir o navegador que a pessoa acabou de fechar.
                _store.update_publication(pub_id, state="fila", error="")
                state_update(paused=True)
        except Exception as e:  # noqa: BLE001
            self._guardar_debug(page, pub_id)
            _store.update_publication(pub_id, state="erro", error=str(e)[:500] or "Falha inesperada.")
            self.falhas_seguidas += 1
            if self.falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                state_update(paused=True)
                self.falhas_seguidas = 0
        finally:
            self.current = None
            self.attention = None
            minutos = max(0.5, float(state_get("interval_min") or 3))
            self.next_at = time.time() + minutos * 60 * random.uniform(0.85, 1.3)

    def _guardar_debug(self, page, pub_id):
        """Foto e HTML da tela no momento do erro, para ajustar o roteiro."""
        try:
            pasta = _debug_dir()
            pasta.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(pasta / f"{pub_id}.jpg"), type="jpeg", quality=70)
            (pasta / f"{pub_id}.html").write_text(page.content(), encoding="utf-8")
            antigos = sorted(pasta.iterdir(), key=lambda p: p.stat().st_mtime)
            for p in antigos[:-40]:
                p.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    # -- gravacao ------------------------------------------------------------

    def _on_record(self, source, evento):
        rec = self.recording
        if not rec or not isinstance(evento, dict):
            return
        self.touch()
        # A foto sai um pouco depois do clique, para mostrar o que ele abriu.
        rec["pendentes"].append((time.monotonic() + 1.5, evento, source.get("page")))

    def _on_file_chooser(self, chooser):
        """Sem isto o seletor de arquivo nativo abriria numa tela que ninguem ve."""
        if not self.recording:
            return
        amostra = _video_de_amostra()
        if amostra:
            try:
                chooser.set_files(str(amostra))
                self._registrar({"tipo": "seletor_de_arquivo", "arquivo": amostra.name,
                                 "multiplo": chooser.is_multiple()}, None)
            except Exception as e:  # noqa: BLE001
                self._registrar({"tipo": "seletor_de_arquivo", "erro": str(e)}, None)

    def _registrar(self, evento, page):
        rec = self.recording
        if not rec:
            return
        rec["n"] += 1
        base = rec["dir"] / f"{rec['n']:03d}"
        evento = {**evento, "quando": _now()}
        url = (evento.get("url") or (page.url if page else "") or "").lower()
        # Tela de login nao e fotografada: o roteiro nao precisa dela.
        login = any(p in url for p in ("/account/login", "/login", "/passport"))
        if page is not None and not login and not evento.get("senha"):
            try:
                page.screenshot(path=str(base) + ".jpg", type="jpeg", quality=70)
                evento["url_depois"] = page.url
                (base.parent / (base.name + ".html")).write_text(page.content(), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                evento["erro_foto"] = str(e)
        (base.parent / (base.name + ".json")).write_text(
            json.dumps(evento, ensure_ascii=False, indent=1), encoding="utf-8")

    def _drenar_gravacao(self, context):
        rec = self.recording
        if not rec:
            return
        if self._snapshot_pedido:
            self._snapshot_pedido = False
            self._registrar({"tipo": "captura_manual"}, self._work_page(context))
        agora = time.monotonic()
        prontos = [p for p in rec["pendentes"] if p[0] <= agora]
        rec["pendentes"] = [p for p in rec["pendentes"] if p[0] > agora]
        for _, evento, page in prontos:
            if page is None or page.is_closed():
                page = self._work_page(context)
            self._registrar(evento, page)

    # -- visor --------------------------------------------------------------

    def viewer(self):
        if not self.open or not self.endpoint:
            return None
        with self._lock:
            if self._viewer is None or not self._viewer.alive():
                self._viewer = _Viewer(self.endpoint)
            return self._viewer

    def _stop_viewer(self):
        with self._lock:
            if self._viewer:
                self._viewer.stop = True
            self._viewer = None


class _Publicacao:
    """O roteiro de um video, passo a passo, na pagina da Central."""

    def __init__(self, browser, page, pub, output, caminho):
        self.b = browser
        self.page = page
        self.pub = pub
        self.output = output
        self.caminho = caminho
        self.conta = (pub.get("target") or "").strip().lstrip("@")
        pedidos = pub.get("product_ids") or []
        self.produto = str(pedidos[0]).strip() if pedidos else ""
        self.clicou_publicar = False

    # -- utilitarios --------------------------------------------------------

    def js(self, body, arg=None):
        return self.page.evaluate(f"(arg) => {{ {JS_HELPERS}\n{body} }}", arg)

    def etapa(self, texto):
        if self.b.current:
            self.b.current["step"] = texto

    def pausa(self, a=0.35, b=0.9):
        self.page.wait_for_timeout(random.uniform(a, b) * 1000)

    def clicar(self, alvo):
        if not alvo:
            return False
        x = alvo["x"] + random.uniform(-alvo["w"] / 6, alvo["w"] / 6)
        y = alvo["y"] + random.uniform(-alvo["h"] / 6, alvo["h"] / 6)
        self.page.mouse.move(x, y, steps=random.randint(6, 14))
        self.pausa(0.08, 0.25)
        self.page.mouse.click(x, y)
        return True

    def clicar_texto(self, texto, preferir="", contains=False):
        """Clica no elemento visivel e desobstruido com este texto.

        ``preferir='button'`` fica com o que for botao; ``'ultimo'``, com o mais
        baixo da tela (o rodape da gaveta, por exemplo).
        """
        alvo = self.js(
            """
            let els = byText(arg.t, {contains: arg.c}).filter((el) => !disabled(el));
            if (arg.p === 'button') {
              let bts = els.filter((el) => el.closest('button, [role="button"]'));
              if (!bts.length) {
                // Botao com icone ou "+" no texto: "+ Adicionar produto".
                bts = byText(arg.t, {contains: true})
                  .map((el) => el.closest('button, [role="button"]'))
                  .filter((el) => el && !disabled(el) && norm(el.innerText).length <= norm(arg.t).length + 4);
              }
              if (bts.length) els = bts;
            }
            if (arg.p === 'ultimo') {
              els.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
            }
            return clickableBox(els);
            """,
            {"t": texto, "p": preferir, "c": contains},
        )
        return self.clicar(alvo)

    def visivel(self, texto, contains=False):
        return bool(self.js("return byText(arg.t, {contains: arg.c}).length > 0;",
                            {"t": texto, "c": contains}))

    def _precisa_login(self):
        url = (self.page.url or "").lower()
        return any(p in url for p in ("/account/login", "/login", "/passport", "/register"))

    def _tem_captcha(self):
        try:
            return bool(self.js("return hasCaptcha();"))
        except Exception:  # noqa: BLE001
            return False

    def fechar_avisos(self):
        """Balões de novidade da Central ("Entendi") cobrem os botões.

        So clica dentro de popover/guia: um "Entendi" solto na pagina pode ser
        outra coisa.
        """
        try:
            alvo = self.js(
                """
                const els = ['Entendi', 'Ok, entendi', 'Pular', 'Agora não', 'Fechar']
                  .flatMap((t) => byText(t))
                  .map(asButton)
                  .filter((el) => el.closest('[class*="popover" i], [class*="guide" i], [class*="tour" i], [class*="onboard" i], [class*="coach" i]'));
                return clickableBox(els);
                """
            )
        except Exception:  # noqa: BLE001
            return False
        if alvo:
            self.clicar(alvo)
            self.pausa(0.4, 0.8)
            return True
        return False

    def vigiar(self):
        """Em toda espera: fechar pedido, login caiu, verificacao anti-robo."""
        self.b._check_abort()
        agora = time.monotonic()
        if agora - getattr(self, "_ultimo_aviso", 0) > 3:
            self._ultimo_aviso = agora
            self.fechar_avisos()
        if self._precisa_login():
            self.pedir_ajuda(
                "Entre na sua conta TikTok Seller no navegador abaixo. "
                "Depois a publicação segue sozinha.",
                pronto=lambda: not self._precisa_login(),
                tipo="login",
            )
        if self._tem_captcha():
            self.pedir_ajuda(
                "O TikTok pediu uma verificação de segurança. Resolva no "
                "navegador abaixo e a publicação continua.",
                pronto=lambda: not self._tem_captcha(),
                tipo="captcha",
            )

    def esperar(self, cond, timeout, oque):
        limite = time.monotonic() + timeout
        while True:
            self.vigiar()
            try:
                r = cond()
            except Exception:  # noqa: BLE001 -- pagina trocando no meio da leitura
                r = None
            if r:
                return r
            if time.monotonic() > limite:
                raise StepError(f"Não encontrei {oque}.")
            self.page.wait_for_timeout(450)

    def pedir_ajuda(self, mensagem, pronto, tipo="passo", timeout=ATTENTION_TIMEOUT):
        """Para e espera a pessoa agir no visor.

        Sai quando ``pronto()`` fica verdadeiro, ou quando a pessoa responde:
        continuar (tenta de novo), pular, ou "ja publicou".
        """
        self.b.attention = {"message": mensagem, "kind": tipo}
        limite = time.monotonic() + timeout
        try:
            while time.monotonic() < limite:
                self.b._check_abort()
                try:
                    resposta = self.b.replies.get_nowait()
                except queue.Empty:
                    resposta = None
                if resposta == "abort":
                    raise Abort()
                if resposta == "pular":
                    raise Skip()
                if resposta == "publicado":
                    raise MarkedDone()
                try:
                    ok = pronto()
                except Exception:  # noqa: BLE001
                    ok = False
                if ok or resposta == "continuar":
                    return
                self.page.wait_for_timeout(700)
            raise StepError("Ninguém resolveu a tempo: " + mensagem)
        finally:
            self.b.attention = None

    def passo(self, nome, feito, fazer, ajuda, timeout=25, sempre=False):
        """Tenta o passo sozinho; se nao der, pede para a pessoa fazer no visor.

        ``sempre`` executa ``fazer`` mesmo se ``feito`` ja parecer verdadeiro.
        """
        self.etapa(nome)
        if not sempre:
            r = self._seguro(feito)
            if r:
                return r
        try:
            fazer()
            return self.esperar(feito, timeout, nome.lower())
        except (Abort, Skip, MarkedDone):
            raise
        except Exception as e:  # noqa: BLE001 -- qualquer tropeco vira pedido de ajuda
            # No log do container: e por aqui que se ajusta o roteiro quando o
            # site do TikTok muda.
            print(f"[seller] passo '{nome}' nao saiu sozinho: {e}", flush=True)
        mensagem = f"{ajuda} Depois toque em Continuar."
        while True:
            self.pedir_ajuda(mensagem, pronto=lambda: self._seguro(feito))
            r = self._seguro(feito)
            if r:
                return r
            mensagem = f"Ainda não detectei este passo. {ajuda} Depois toque em Continuar."

    def _seguro(self, fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001 -- pagina trocando no meio da leitura
            return None

    # -- o roteiro ----------------------------------------------------------

    def run(self):
        self.pagina_de_videos()
        self.abrir_envio()
        self.enviar_arquivo()
        self.escolher_conta()
        produto = self.vincular_produto()
        self.escrever_legenda()
        self.publicar()
        return produto

    # 1. "Videos com produtos a venda"
    def _na_pagina_de_videos(self):
        na_pagina = "/shoppable-videos" in (self.page.url or "") or self.visivel(
            "Vídeos com produtos à venda")
        return na_pagina and self.js("return byText('Publicar no TikTok').some(onTop);")

    def pagina_de_videos(self):
        def fazer():
            destino = shop_get(self.b.shop, "video_url") or SELLER_VIDEOS
            self.page.goto(destino, wait_until="domcontentloaded", timeout=60_000)
            self.pausa(1.5, 2.5)
            self.vigiar()
            self.fechar_avisos()
            if self._na_pagina_de_videos():
                return
            # Pelo menu: "LIVE e vídeo" > "Vídeos com produtos à venda".
            if not self.clicar_texto("Vídeos com produtos à venda"):
                self.clicar_texto("LIVE e vídeo")
                self.pausa(0.8, 1.4)
                self.clicar_texto("Vídeos com produtos à venda")

        # Sempre recarrega: sobra de um video anterior (gaveta aberta, video
        # meio enviado) nao pode contaminar este.
        self.passo(
            "Abrindo Vídeos com produtos à venda",
            self._na_pagina_de_videos,
            fazer,
            "Abra “LIVE e vídeo” › “Vídeos com produtos à venda” no navegador.",
            timeout=40,
            sempre=True,
        )
        # Guarda o endereco: da proxima vez vai direto, sem passar pelo menu.
        url = self.page.url
        if url and url.startswith(SELLER_ORIGIN) and url != shop_get(self.b.shop, "video_url"):
            shop_update(self.b.shop, video_url=url, last_login_ok=_now())

    # 2. "Publicar no TikTok" > "Publicação de vídeo"
    def _gaveta_de_envio(self):
        return self.js(
            """
            return byText('Escolha um vídeo para carregar').length > 0
              || byText('Carregue um vídeo com produtos à venda').length > 0
              || byText('Escolher vídeo').length > 0;
            """
        )

    def abrir_envio(self):
        def fazer():
            self.fechar_avisos()
            self.clicar_texto("Publicar no TikTok", preferir="button")
            self.pausa(0.6, 1.1)
            self.esperar(lambda: self.visivel("Publicação de vídeo"), 8, "o menu Publicação de vídeo")
            self.clicar_texto("Publicação de vídeo")

        self.passo(
            "Abrindo o envio de vídeo",
            self._gaveta_de_envio,
            fazer,
            "Clique em “Publicar no TikTok” › “Publicação de vídeo” no navegador.",
        )

    # 3. o arquivo
    def _formulario_aberto(self):
        return self.visivel("Contas de publicação")

    def enviar_arquivo(self):
        self.etapa("Enviando o vídeo")
        entrada = self.page.locator('input[type="file"][accept*="video"]')
        if entrada.count() == 0:
            entrada = self.page.locator('input[type="file"]')
        if entrada.count():
            entrada.first.set_input_files(str(self.caminho))
        else:
            # Sem <input> na pagina: o seletor de arquivo so nasce no clique.
            with self.page.expect_file_chooser(timeout=15_000) as escolha:
                if not self.clicar_texto("Escolher vídeo", preferir="button"):
                    raise StepError("Não encontrei o botão Escolher vídeo.")
            escolha.value.set_files(str(self.caminho))
        self.etapa("Esperando o TikTok receber o vídeo")
        # Video grande em conexao lenta demora; 10 minutos e folga.
        self.esperar(self._formulario_aberto, 600, "o formulário depois do envio do vídeo")
        self.pausa(1.0, 2.0)

    # 4. a conta
    def _seletor_de_conta(self):
        return self.js(
            """
            const rotulo = byText('Contas de publicação')[0];
            if (!rotulo) return null;
            let caixa = null;
            // No site real (gravado em 2026-09-26) o seletor e um <div> com
            // cursor-pointer dentro do item recolhivel da secao, nao um select.
            for (let e = rotulo, i = 0; e && i < 10 && !caixa; e = e.parentElement, i++) {
              if (!/collapse-item/.test(e.className || '') || /header/.test(e.className || '')) continue;
              caixa = Array.from(e.querySelectorAll('[class*="cursor-pointer"]')).find(shown) || null;
            }
            for (let e = rotulo, i = 0; e && i < 6 && !caixa; e = e.parentElement, i++) {
              const achados = Array.from(e.querySelectorAll('[role="combobox"], [class*="select" i]'))
                .filter((x) => shown(x) && x.getBoundingClientRect().top >= rotulo.getBoundingClientRect().bottom - 2);
              // O mais externo: o que abre a lista, nao o texto dentro dele.
              caixa = achados.find((x) => !achados.some((o) => o !== x && o.contains(x))) || null;
            }
            if (!caixa) return null;
            const b = box(caixa);
            const r = caixa.getBoundingClientRect();
            return { ...b, left: r.left, right: r.right, bottom: r.bottom, valor: norm(caixa.innerText) };
            """
        )

    def _conta_certa(self):
        sel = self._seletor_de_conta()
        return bool(sel) and sel["valor"].split(" ")[0] == self.conta.lower()

    def _ler_contas_abertas(self, sel):
        return self.js(
            """
            const vistos = new Set();
            // Lista aberta: cada conta e um [role=option] ("gabrielatoffa
            // Marketing Toffa Decor"); o @ e a primeira palavra.
            for (const op of document.querySelectorAll('[role="option"]')) {
              const t = norm(op.innerText).split(' ')[0];
              if (shown(op) && /^[a-z0-9._]{2,40}$/.test(t)) vistos.add(t);
            }
            if (vistos.size) return Array.from(vistos);
            for (const el of document.querySelectorAll('body *')) {
              if (el.children.length) continue;
              const t = (el.textContent || '').trim();
              if (!/^[a-z0-9._]{2,40}$/.test(t) || ['oficial', 'marketing'].includes(t)) continue;
              if (!shown(el)) continue;
              const r = el.getBoundingClientRect();
              if (r.top < arg.bottom - 2 || r.top > arg.bottom + 600) continue;
              if (r.left < arg.left - 10 || r.right > arg.right + 10) continue;
              vistos.add(t);
            }
            return Array.from(vistos);
            """,
            sel,
        ) or []

    def escolher_conta(self):
        if not self.conta:
            return
        self.etapa(f"Escolhendo a conta @{self.conta}")
        self.esperar(self._seletor_de_conta, 20, "o seletor de conta")

        def fazer():
            atual = self._seletor_de_conta()
            self.clicar(atual)
            self.pausa(0.6, 1.0)
            _remember_accounts(self.b.shop, self._ler_contas_abertas(atual))
            opcao = self.js(
                """
                const conta = norm(arg.conta);
                const ops = Array.from(document.querySelectorAll('[role="option"]'))
                  .filter((op) => shown(op) && norm(op.innerText).split(' ')[0] === conta);
                if (ops.length) return clickableBox(ops);
                const alvos = byText(arg.conta).filter((el) => {
                  const r = el.getBoundingClientRect();
                  return r.top > arg.bottom - 2 && r.left >= arg.left - 10 && r.right <= arg.right + 10;
                });
                return clickableBox(alvos);
                """,
                {**atual, "conta": self.conta},
            )
            if not opcao:
                self.page.keyboard.press("Escape")
                raise StepError(f"A conta @{self.conta} não aparece na lista.")
            self.clicar(opcao)
            self.pausa(0.5, 0.9)

        self.passo(
            f"Escolhendo a conta @{self.conta}",
            self._conta_certa,
            fazer,
            f"Escolha a conta @{self.conta} em “Contas de publicação”.",
        )

    # 5. o produto (carrinho laranja)
    def _produto_vinculado(self):
        """O ID do produto que ja esta no formulario (e o modal ja fechou)."""
        return self.js(
            """
            if (byText('Escolha o produto').length) return null;
            const cartao = document.getElementById('link-product-item');
            if (cartao) {
              for (const el of cartao.querySelectorAll('*')) {
                const t = (el.textContent || '').trim();
                if (!el.children.length && /^\\d{12,22}$/.test(t) && shown(el)) return t;
              }
            }
            // So dentro da secao Produto do formulario: o ID aparece no cartao
            // logo abaixo de "Adicionar produto".
            for (const rotulo of byText('Adicionar produto', {contains: true})) {
              for (let e = rotulo, i = 0; e && i < 6; e = e.parentElement, i++) {
                for (const el of e.querySelectorAll('*')) {
                  if (el.children.length) continue;
                  const t = (el.textContent || '').trim();
                  if (/^\\d{12,22}$/.test(t) && shown(el)) return t;
                }
              }
            }
            return null;
            """
        )

    def _linhas_do_modal(self):
        return self.js(
            """
            const titulo = byText('Escolha o produto')[0];
            if (!titulo) return null;
            let modal = titulo;
            while (modal.parentElement && !modal.querySelector('input[placeholder]')) modal = modal.parentElement;
            const linhas = [];
            for (const el of modal.querySelectorAll('*')) {
              if (el.children.length) continue;
              const t = (el.textContent || '').trim();
              if (!/^\\d{12,22}$/.test(t) || !shown(el)) continue;
              let linha = el.closest('tr, [role="row"]');
              if (!linha) {
                linha = el;
                while (linha.parentElement && linha.parentElement !== modal
                       && !linha.querySelector('input[type="radio"], [class*="radio" i]')) linha = linha.parentElement;
              }
              const radio = linha.querySelector('input[type="radio"], [class*="radio" i]');
              let alvo = radio;
              if (alvo && !shown(alvo)) alvo = alvo.parentElement;
              const partes = (linha.innerText || '').split(/[\\n\\t]/).map((s) => s.trim()).filter(Boolean);
              const nome = partes.find((s) => s !== t && !/^r\\$/i.test(s) && !/^\\d+$/.test(s)) || '';
              linhas.push({ id: t, title: nome, alvo: box(alvo && shown(alvo) ? alvo : linha) });
            }
            return linhas;
            """
        )

    def vincular_produto(self):
        self.etapa("Vinculando o produto")
        if not self.produto:
            # Sem produto informado: a pessoa escolhe no visor, e o app lembra.
            self.clicar_texto("Adicionar produto", preferir="button")
            r = self.passo(
                "Esperando você escolher o produto",
                self._produto_vinculado,
                lambda: None,
                "Escolha o produto deste vídeo no navegador e confirme.",
                timeout=1,
            )
            self._lembrar(r)
            return r

        def fazer():
            self.clicar_texto("Adicionar produto", preferir="button")
            self.esperar(lambda: self.visivel("Escolha o produto"), 15, "a janela Escolha o produto")
            self.pausa(0.8, 1.4)
            busca = self.js(
                """
                const i = Array.from(document.querySelectorAll('input[placeholder]'))
                  .find((x) => /id do produto|nome ou id/i.test(x.placeholder) && shown(x));
                return i ? box(i) : null;
                """
            )
            if not busca:
                raise StepError("o campo de busca de produto")
            self.clicar(busca)
            self.page.keyboard.press("ControlOrMeta+a")
            self.page.keyboard.press("Backspace")
            self.page.keyboard.insert_text(self.produto)
            self.pausa(0.2, 0.4)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(2500)
            linhas = self.esperar(lambda: self._linhas_do_modal() or None, 15, "o produto na busca")
            escolhida = self._escolher_linha(linhas)
            if not escolhida:
                raise StepError(
                    f"A busca por “{self.produto}” trouxe {len(linhas)} produtos e não sei qual é."
                )
            self.clicar(escolhida["alvo"])
            self.pausa(0.5, 0.9)
            self.clicar_texto("Confirmar", preferir="button")
            self.pausa(0.8, 1.2)

        r = self.passo(
            "Vinculando o produto",
            self._produto_vinculado,
            fazer,
            f"Escolha o produto “{self.produto}” no navegador (Adicionar produto › marcar › Confirmar).",
        )
        self._lembrar(r)
        return r

    def _escolher_linha(self, linhas):
        alvo = self.produto.strip().lower()
        if PRODUCT_ID_RE.match(alvo):
            return next((l for l in linhas if l["id"] == alvo), None)
        exatas = [l for l in linhas if l["title"].strip().lower() == alvo]
        if len(exatas) == 1:
            return exatas[0]
        if len(linhas) == 1:
            return linhas[0]
        return None

    def _lembrar(self, product_id):
        if not product_id:
            return
        titulo = self.js(
            """
            for (const el of document.querySelectorAll('body *')) {
              if (el.children.length || (el.textContent || '').trim() !== arg) continue;
              const card = el.parentElement && el.parentElement.parentElement;
              const partes = (card ? card.innerText : '').split('\\n').map((s) => s.trim()).filter(Boolean);
              return partes.find((s) => s !== arg && !/^editar$/i.test(s)) || '';
            }
            return '';
            """,
            product_id,
        ) or ""
        remember_product(self.b.shop, product_id, titulo, self.output)

    # 6. legenda e hashtags
    def _texto_da_legenda(self):
        legenda = (self.output.get("caption") or self.output.get("phrase") or "").strip()
        return legenda[:2900]

    def _lista_hashtags(self):
        tags = [t.strip().lstrip("#") for t in (self.output.get("hashtags") or []) if t.strip()]
        return tags[:10]

    def _hashtags(self):
        return " ".join("#" + t for t in self._lista_hashtags())[:950]

    # Seletores diretos vistos no site real; o rotulo fica de reserva.
    CAMPOS = {
        "Descrição": '#video_desc_input, textarea.post-to-tt-video-desc-textarea',
        "Hashtags": 'input.content-arco-input-tag-input, input[placeholder*="hashtag" i]',
    }

    def _campo(self, rotulo):
        return self.js(
            """
            const direto = arg.sel && Array.from(document.querySelectorAll(arg.sel)).find(shown);
            if (direto) return { ...box(direto), valor: fieldValue(direto) };
            const r = byText(arg.rotulo)[0];
            const f = r && fieldNear(r);
            return f ? { ...box(f), valor: fieldValue(f) } : null;
            """,
            {"rotulo": rotulo, "sel": self.CAMPOS.get(rotulo, "")},
        )

    def _legenda_ok(self):
        texto = self._texto_da_legenda()
        campo = self._campo("Descrição")
        if not campo:
            return False
        inicio = " ".join(texto.lower().split())[:40]
        return campo["valor"].startswith(inicio)

    def _hashtags_ok(self):
        tags = self._lista_hashtags()
        if not tags:
            return True
        # Campo de fichas (arco input-tag): cada Enter vira uma ficha.
        fichas = self.js(
            """
            return Array.from(document.querySelectorAll('[class*="input-tag-tag"]'))
              .filter(shown).map((el) => norm(el.innerText).replace(/^#/, ''));
            """
        ) or []
        if fichas:
            return all(t.lower() in fichas for t in tags)
        # Sem fichas: campo de texto comum. So vale o valor dele -- procurar o
        # texto na pagina achava "decor" em "Toffa Decor" e pulava as hashtags.
        campo = self._campo("Hashtags")
        return bool(campo) and tags[0].lower() in campo["valor"]

    def _preencher_fichas(self, rotulo, tags):
        campo = self.esperar(lambda: self._campo(rotulo), 15, f"o campo {rotulo}")
        self.clicar(campo)
        self.pausa(0.2, 0.4)
        ja = self.js(
            """
            return Array.from(document.querySelectorAll('[class*="input-tag-tag"]'))
              .filter(shown).map((el) => norm(el.innerText).replace(/^#/, ''));
            """
        ) or []
        for tag in tags:
            if tag.lower() in ja:
                continue
            self.page.keyboard.type(tag, delay=random.randint(30, 70))
            self.pausa(0.15, 0.3)
            self.page.keyboard.press("Enter")
            self.pausa(0.3, 0.6)

    def _preencher(self, rotulo, texto, digitar=False):
        campo = self.esperar(lambda: self._campo(rotulo), 15, f"o campo {rotulo}")
        self.clicar(campo)
        self.pausa(0.2, 0.4)
        self.page.keyboard.press("ControlOrMeta+a")
        self.page.keyboard.press("Backspace")
        if digitar:
            # Tecla por tecla: campo de hashtag costuma virar ficha no espaco.
            self.page.keyboard.type(texto + " ", delay=random.randint(25, 60))
        else:
            self.page.keyboard.insert_text(texto)
        self.pausa(0.3, 0.6)

    def escrever_legenda(self):
        texto = self._texto_da_legenda()
        if texto:
            # Depois do produto: vincular o produto reescreve a descricao com o
            # nome dele.
            self.passo(
                "Escrevendo a legenda",
                self._legenda_ok,
                lambda: self._preencher("Descrição", texto),
                "Cole a legenda do vídeo no campo Descrição.",
            )
        if self._hashtags():
            self.passo(
                "Escrevendo as hashtags",
                self._hashtags_ok,
                lambda: self._preencher_fichas("Hashtags", self._lista_hashtags()),
                "Escreva as hashtags do vídeo no campo Hashtags.",
            )

    # 7. publicar
    def _publicou(self):
        # No site real a gaveta continua aberta e sobe um modal "Seu vídeo foi
        # publicado" (Abrir o TikTok / Carregar vídeo).
        if self.visivel("Seu vídeo foi publicado"):
            return True
        return not self._formulario_aberto() and not self.visivel("Escolher vídeo")

    def _erro_na_tela(self):
        return self.js(
            """
            const sels = '[role="alert"], [class*="toast" i], [class*="message-error" i], [class*="notification" i]';
            for (const el of document.querySelectorAll(sels)) {
              const t = (el.innerText || '').trim();
              if (t && shown(el) && /(erro|falh|não foi possível|nao foi possivel|tente novamente|inválid)/i.test(t)) return t.slice(0, 300);
            }
            return null;
            """
        )

    def publicar(self):
        self.etapa("Publicando")
        self.vigiar()
        if not self.clicar_texto("Publicar no TikTok", preferir="ultimo"):
            self.pedir_ajuda(
                "Não achei o botão “Publicar no TikTok” da gaveta. Clique nele no navegador.",
                pronto=self._publicou,
            )
            self.clicou_publicar = True
            if not self._seguro(self._publicou):
                raise StepError("A publicação não foi concluída.")
            return
        self.clicou_publicar = True
        confirmou = False
        limite = time.monotonic() + 300
        while time.monotonic() < limite:
            self.vigiar()
            self.page.wait_for_timeout(1000)
            if self._publicou():
                return
            erro = self._erro_na_tela()
            if erro:
                raise StepError(f"O TikTok recusou: {erro}")
            # Uma confirmacao depois do clique ("Publicar?"), uma vez so.
            if not confirmou:
                for texto in ("Confirmar", "Publicar"):
                    if self.clicar_texto(texto, preferir="button"):
                        confirmou = True
                        break
        self.pedir_ajuda(
            "Não consegui confirmar se o vídeo foi publicado. Olhe o navegador: se "
            "saiu, toque em “Já publicou”; se não, conclua por lá ou pule.",
            pronto=self._publicou,
        )
        if not self._seguro(self._publicou):
            raise StepError("Não deu para confirmar a publicação.")


# ---------------------------------------------------------------------------
# visor remoto
# ---------------------------------------------------------------------------

class _Viewer:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.commands = queue.Queue(maxsize=200)
        self.lock = threading.Lock()
        self.frame = None
        self.url = ""
        self.pages = []
        self.active = None
        self.loading = False
        self.error = ""
        self.stop = False
        self.selected = None
        self._seen = {}
        self._last_view = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="tiktok-seller-viewer", daemon=True)
        self._thread.start()

    def alive(self):
        return self._thread.is_alive() and not self.stop

    def watched(self):
        return time.monotonic() - self._last_view < VIEWER_IDLE_SECONDS

    def get_frame(self):
        self._last_view = time.monotonic()
        with self.lock:
            return self.frame

    def send(self, command):
        self._last_view = time.monotonic()
        try:
            self.commands.put_nowait(command)
        except queue.Full:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                pass
            self.commands.put_nowait(command)

    def _escolher_aba(self, abas):
        for aba in abas:
            if aba["id"] not in self._seen:
                self._seen[aba["id"]] = len(self._seen) + 1
                # Aba nova (janela de login, por exemplo) vai para a frente.
                self.selected = aba["id"]
        ids = {a["id"] for a in abas}
        for k in list(self._seen):
            if k not in ids:
                self._seen.pop(k, None)
        if self.selected not in ids:
            self.selected = max(ids, key=lambda k: self._seen.get(k, 0)) if ids else None
        return self.selected

    def _executar(self, cdp, cmd):
        tipo = cmd.get("type")
        cx = lambda v: max(0.0, min(float(WIDTH), float(v or 0)))  # noqa: E731
        cy = lambda v: max(0.0, min(float(HEIGHT), float(v or 0)))  # noqa: E731
        if tipo == "click":
            cdp.click(cx(cmd.get("x")), cy(cmd.get("y")), cmd.get("button", "left"))
        elif tipo in ("down", "up"):
            cdp.move(cx(cmd.get("x")), cy(cmd.get("y")))
            (cdp.down if tipo == "down" else cdp.up)(cmd.get("button", "left"))
        elif tipo == "move":
            for x, y, atraso in cmd.get("path") or [(cmd.get("x", 0), cmd.get("y", 0), 0)]:
                if atraso:
                    time.sleep(min(float(atraso), 200) / 1000)
                cdp.move(cx(x), cy(y))
        elif tipo == "wheel":
            cdp.wheel(float(cmd.get("delta_x", 0)), float(cmd.get("delta_y", 0)))
        elif tipo == "text":
            cdp.insert_text(str(cmd.get("text", ""))[:2000])
        elif tipo == "key":
            tecla = str(cmd.get("key", ""))[:80]
            if tecla:
                cdp.press(tecla)
        elif tipo == "navigate":
            # Destinos fixos: o visor nao pode virar um proxy aberto.
            acao = cmd.get("action")
            if acao == "home":
                cdp.navigate(shop_get(BROWSER.shop, "video_url") or SELLER_VIDEOS)
            elif acao == "back":
                cdp.back()
            elif acao == "reload":
                cdp.reload()

    def _run(self):
        cdp = None
        try:
            cdp = CdpBrowser(self.endpoint)
            while not self.stop and self.watched():
                abas = cdp.tabs()
                alvo = self._escolher_aba(abas)
                while True:
                    try:
                        cmd = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if cmd.get("type") == "select_page":
                        if any(a["id"] == cmd.get("page_id") for a in abas):
                            self.selected = alvo = cmd.get("page_id")
                        continue
                    if cmd.get("page_id") and cmd.get("page_id") != cdp.target:
                        continue  # clique pensado para outra aba
                    try:
                        if alvo and cdp.target != alvo:
                            cdp.attach(alvo)
                        self._executar(cdp, cmd)
                    except CdpError as e:
                        self.error = str(e)
                frame = None
                pronto = "loading"
                try:
                    if alvo and (cdp.target != alvo or not cdp.attached):
                        cdp.attach(alvo)
                    if alvo:
                        frame = cdp.screenshot()
                        pronto = cdp.evaluate("document.readyState")
                except CdpError:
                    pass  # a aba esta trocando de pagina: fica o quadro anterior
                with self.lock:
                    if frame:
                        self.frame = frame
                        self.error = ""
                    self.pages = [{"id": a["id"], "url": a["url"]} for a in abas]
                    self.active = cdp.target
                    self.url = next((a["url"] for a in abas if a["id"] == cdp.target), "")
                    self.loading = pronto != "complete"
                time.sleep(FRAME_INTERVAL)
        except Exception as e:  # noqa: BLE001
            if not self.stop:
                self.error = str(e)
        finally:
            self.stop = True
            if cdp:
                cdp.close()


# ---------------------------------------------------------------------------
# API do modulo (chamada pelas rotas do app.py)
# ---------------------------------------------------------------------------

BROWSER = SellerBrowser()


def init(store_module, data_dir, output_dir):
    global _store, _data_dir, _output_dir
    _store = store_module
    _data_dir = Path(data_dir)
    _output_dir = Path(output_dir)
    _importar_json_antigo()
    # Um video que estava no meio da publicacao quando o app caiu: nao da para
    # saber se saiu. Melhor dizer isso do que publicar duas vezes.
    for pub in _store.shop_publications(states=("enviando",)):
        _store.update_publication(
            pub["id"], state="erro",
            error="O app reiniciou no meio desta publicação. Confira no TikTok Seller "
                  "se o vídeo saiu antes de tentar de novo.",
        )
    if _has_work() and not state_get("paused"):
        BROWSER.ensure_started()


def _has_work():
    return bool(_store and _store.shop_queue())


def busy():
    """Para o /api/health: so o video que esta no meio da publicacao conta.

    A fila em si sobrevive a um reinicio (esta no SQLite).
    """
    return 1 if BROWSER.current else 0


def _session_configured(shop):
    if not shop:
        return False
    perfil = _profile_dir(shop)
    return (perfil / "Default" / "Cookies").exists() or (perfil / "Default" / "Network" / "Cookies").exists()


def shops_view():
    contagem = _store.count_shop_products() if _store else {}
    lojas = []
    for k in shop_keys():
        aberta = BROWSER.open and BROWSER.shop == k
        lojas.append({
            "key": k,
            "name": shop_name(k),
            "named": bool(shop_get(k, "name")),
            "seller_id": shop_get(k, "seller_id"),
            "code": shop_get(k, "code"),
            "configured": _session_configured(k),
            "open": aberta,
            "products": contagem.get(k, 0),
            "synced_at": shop_get(k, "products_synced_at") or "",
            "last_login_ok": shop_get(k, "last_login_ok") or "",
            "accounts": accounts_view(k),
            "sync": BROWSER.sync if BROWSER.sync.get("shop") == k else None,
        })
    return lojas


def status():
    ok, hint = playwright_available()
    viewer = BROWSER._viewer if BROWSER._viewer and BROWSER._viewer.alive() else None
    url = (viewer.url if viewer else "") or BROWSER.page_url
    precisa_login = any(p in (url or "").lower() for p in ("/account/login", "/login", "/passport"))
    atual = dict(BROWSER.current) if BROWSER.current else None
    fila = _store.shop_queue() if _store else []
    if not ok:
        mensagem = hint
    elif BROWSER.error and not BROWSER.open:
        mensagem = BROWSER.error
    elif BROWSER.attention:
        mensagem = BROWSER.attention["message"]
    elif atual:
        mensagem = f"{atual['step']}..."
    elif BROWSER.starting:
        mensagem = "Abrindo o navegador..."
    elif BROWSER.open and precisa_login:
        mensagem = "Entre na conta TikTok Seller desta loja e depois toque em Concluir."
    elif BROWSER.open:
        mensagem = f"Navegador aberto em “{shop_name(BROWSER.shop)}”."
    elif shop_keys():
        mensagem = "Logins salvos neste servidor."
    else:
        mensagem = "Nenhuma loja TikTok Seller conectada ainda."
    return {
        "available": ok,
        "message": mensagem,
        "error": BROWSER.error,
        "attention": BROWSER.attention,
        "browser": {
            "open": BROWSER.open,
            "starting": BROWSER.starting,
            "url": url,
            "pages": viewer.pages if viewer else [],
            "active_page_id": viewer.active if viewer else None,
            "loading": bool(viewer and viewer.loading),
            "width": WIDTH,
            "height": HEIGHT,
            "needs_login": precisa_login,
            "shop": BROWSER.shop if BROWSER.open or BROWSER.starting else "",
            "shop_name": shop_name(BROWSER.shop) if BROWSER.shop else "",
        },
        "session": {
            "configured": any(_session_configured(k) for k in shop_keys()),
        },
        "shops": shops_view(),
        "queue": {
            "paused": bool(state_get("paused")),
            "pending": len(fila),
            "current": atual,
            "next_at": BROWSER.next_at if fila and BROWSER.next_at > time.time() else 0,
            "interval_min": state_get("interval_min"),
        },
        "accounts": accounts_view(),
        "last_account": state_get("last_account") or "",
        "products_sync": {
            **BROWSER.sync,
            "synced_at": max([shop_get(k, "products_synced_at") or "" for k in shop_keys()] or [""]),
        },
        "recording": (
            {"on": True, "count": BROWSER.recording["n"], "name": BROWSER.recording["dir"].name}
            if BROWSER.recording else {"on": False, "last": _ultima_gravacao_nome()}
        ),
    }


def open_browser(shop=None):
    if shop and not shop_exists(shop):
        raise LookupError("Loja não encontrada.")
    BROWSER.ensure_started(shop or None)
    return status()


def add_shop():
    """Uma loja nova: perfil vazio, e o navegador abre nele para o login."""
    chave = new_shop_key()
    shop_update(chave, created_at=_now())
    BROWSER.ensure_started(chave)
    return chave


def remove_shop(shop):
    import shutil

    if not shop_exists(shop):
        raise LookupError("Loja não encontrada.")
    if any(p.get("shop") == shop for p in _store.shop_publications(states=("fila", "enviando"))):
        raise ValueError("Há vídeos desta loja na fila. Cancele-os antes de remover a loja.")
    if BROWSER.alive() and BROWSER.shop == shop:
        close_browser()
    _store.delete_shop(shop)
    if state_get("active_shop") == shop:
        state_update(active_shop="")
    if (state_get("last_account") or "").startswith(shop + "/"):
        state_update(last_account="")
    _store.forget_shop(shop)
    shutil.rmtree(_profile_dir(shop), ignore_errors=True)


def close_browser():
    BROWSER.request_close()
    if BROWSER._thread:
        BROWSER._thread.join(timeout=15)
    return status()


def frame():
    viewer = BROWSER.viewer()
    return viewer.get_frame() if viewer else None


def send_input(command):
    viewer = BROWSER.viewer()
    if not viewer:
        raise RuntimeError("O navegador do TikTok Seller não está aberto.")
    BROWSER.touch()
    viewer.send(command)


def reply(action):
    if action not in ("continuar", "pular", "publicado"):
        raise ValueError("Ação desconhecida.")
    BROWSER.replies.put(action)


def enqueue(items, account="", interval_min=None, shop=""):
    """items: [{"output_id", "product"}]. Devolve as publicacoes criadas.

    A loja vem junto com a conta; sem ela, sai da conta (se a conta so existe
    numa loja) ou e a unica loja cadastrada.
    """
    conta = (account or "").strip().lstrip("@")
    if conta and not HANDLE_RE.match(conta):
        raise ValueError("Nome de conta inválido.")
    loja = shop or (shop_of_account(conta) if conta else "")
    if not loja and len(shop_keys()) == 1:
        loja = shop_keys()[0]
    if not loja or not shop_exists(loja):
        raise ValueError("Escolha a loja (a conta) que vai publicar.")
    if interval_min is not None:
        state_update(interval_min=max(0.5, min(240.0, float(interval_min))))
    if conta:
        _remember_accounts(loja, [conta])
    state_update(last_account=f"{loja}/{conta}")
    criadas = []
    ocupados = {p["output_id"] for p in _store.shop_publications(states=("fila", "enviando"))}
    for item in items:
        output_id = str(item.get("output_id") or "")
        if not output_id or output_id in ocupados or not _store.get_output(output_id):
            continue
        produto = str(item.get("product") or "").strip()[:200]
        output = _store.get_output(output_id)
        vinculado = _store.product_for_output(output, loja)
        if not produto:
            produto = vinculado
        elif PRODUCT_ID_RE.match(produto) and produto != vinculado:
            # Escolhido na hora de publicar: fica como produto deste video
            # nesta loja.
            _store.set_product_link("output", output_id, loja, produto)
        criadas.append(_store.add_publication(
            output_id=output_id,
            platform=PLATFORM,
            mode="shop",
            product_mode="id" if PRODUCT_ID_RE.match(produto) else ("busca" if produto else "manual"),
            product_ids=[produto] if produto else [],
            target=conta,
            shop=loja,
        ))
        ocupados.add(output_id)
    if criadas:
        state_update(paused=False)
        BROWSER.ensure_started(None if BROWSER.alive() else loja)
    return criadas


def request_sync(shop=None):
    """Pede ao navegador que baixe o catalogo de uma loja (abre se preciso)."""
    loja = shop or BROWSER.shop or state_get("active_shop") or (shop_keys() or [""])[0]
    if not loja or not shop_exists(loja):
        raise LookupError("Loja não encontrada.")
    BROWSER.sync_pedido = loja
    BROWSER.sync = {"running": False, "error": "", "count": 0, "shop": loja}
    BROWSER.ensure_started(None if BROWSER.alive() else loja)
    return status()


def set_paused(paused):
    state_update(paused=bool(paused))
    if not paused:
        BROWSER.next_at = 0
        if _has_work():
            BROWSER.ensure_started()
    return status()


def cancel(pub_id):
    pub = _store.get_publication(pub_id)
    if not pub or pub.get("platform") != PLATFORM:
        raise LookupError("Publicação não encontrada.")
    if pub["state"] != "fila":
        raise ValueError("Só dá para cancelar o que ainda está na fila.")
    _store.update_publication(pub_id, state="cancelado", error="Cancelado por você.")


def retry(pub_id):
    pub = _store.get_publication(pub_id)
    if not pub or pub.get("platform") != PLATFORM:
        raise LookupError("Publicação não encontrada.")
    if pub["state"] not in ("erro", "cancelado"):
        raise ValueError("Esta publicação não está com erro.")
    _store.update_publication(pub_id, state="fila", error="")
    if not state_get("paused"):
        BROWSER.ensure_started()


# ---------------------------------------------------------------------------
# gravacao de uma sessao real, para calibrar o roteiro
# ---------------------------------------------------------------------------

def _gravacoes_dir():
    return _data_dir / "seller_recordings"


def _ultima_gravacao():
    pasta = _gravacoes_dir()
    if not pasta.exists():
        return None
    todas = sorted((p for p in pasta.iterdir() if p.is_dir()), key=lambda p: p.name)
    return todas[-1] if todas else None


def _ultima_gravacao_nome():
    ultima = _ultima_gravacao()
    return ultima.name if ultima else ""


def _video_de_amostra():
    """O video mais recente do acervo, para o envio de teste da gravacao."""
    if not _output_dir or not _output_dir.exists():
        return None
    videos = sorted(
        (p for p in _output_dir.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".webm")),
        key=lambda p: p.stat().st_mtime,
    )
    return videos[-1] if videos else None


def set_recording(on):
    if on:
        if not BROWSER.recording:
            pasta = _gravacoes_dir() / datetime.now().strftime("%Y%m%d-%H%M%S")
            pasta.mkdir(parents=True, exist_ok=True)
            BROWSER.recording = {"dir": pasta, "n": 0, "pendentes": []}
        BROWSER.ensure_started()
    else:
        BROWSER.recording = None
    return status()


def snapshot():
    if not BROWSER.recording:
        raise RuntimeError("A gravação não está ligada.")
    BROWSER._snapshot_pedido = True


def recording_zip():
    """A gravacao mais recente, zipada em memoria."""
    import io
    import zipfile

    pasta = _ultima_gravacao()
    if not pasta:
        return None, ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(pasta.iterdir()):
            z.write(arq, f"{pasta.name}/{arq.name}")
    return buf.getvalue(), f"gravacao-tiktok-seller-{pasta.name}.zip"


def shutdown():
    BROWSER.request_close()
