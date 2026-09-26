"""Catalogo de producao do Studio Native (SQLite).

Ate aqui o app so persistia os videos-fonte (library.json); o que ele *produzia*
existia apenas como arquivo solto em outputs/ mais uma entrada no localStorage do
React. Este modulo cria a entidade que faltava:

    outputs       -> um registro por MP4 renderizado (com legenda e hashtags)
    publications  -> uma linha por tentativa de publicacao de um output
    accounts      -> contas conectadas (TikTok e, no futuro, outras plataformas)

SQLite em vez de mais um JSON porque tres workers (biblioteca, render e a futura
fila de publicacao) escrevem ao mesmo tempo - o padrao de "lock + reescreve o
arquivo inteiro" nao aguenta isso. Vem no Python, sem dependencia nova.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta

import captions as cap

_LOCK = threading.RLock()
_CONN = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS outputs (
    id           TEXT PRIMARY KEY,
    job_id       TEXT,
    library_id   TEXT,
    file         TEXT NOT NULL,
    phrase       TEXT DEFAULT '',
    speech       TEXT DEFAULT '',
    caption      TEXT DEFAULT '',
    hashtags     TEXT DEFAULT '[]',
    theme        TEXT DEFAULT '',
    source_name  TEXT DEFAULT '',
    duration     REAL DEFAULT 0,
    audio_mode   INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'pronto',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outputs_job ON outputs(job_id);
CREATE INDEX IF NOT EXISTS idx_outputs_lib ON outputs(library_id);
CREATE INDEX IF NOT EXISTS idx_outputs_created ON outputs(created_at);

CREATE TABLE IF NOT EXISTS publications (
    id            TEXT PRIMARY KEY,
    output_id     TEXT NOT NULL,
    platform      TEXT DEFAULT 'tiktok',
    account_id    TEXT DEFAULT '',
    publish_id    TEXT DEFAULT '',
    mode          TEXT DEFAULT 'draft',
    privacy       TEXT DEFAULT '',
    product_mode  TEXT DEFAULT 'nenhum',
    product_ids   TEXT DEFAULT '[]',
    state         TEXT DEFAULT 'fila',
    error         TEXT DEFAULT '',
    scheduled_for TEXT DEFAULT '',
    published_at  TEXT DEFAULT '',
    post_url      TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pub_output ON publications(output_id);
CREATE INDEX IF NOT EXISTS idx_pub_state ON publications(state);

-- Pastas. Moram aqui, e nao no library.json, porque valem para os dois lados:
-- os videos-fonte da Biblioteca e os videos produzidos. Duas listas de pastas
-- divergiriam na primeira renomeacao.
CREATE TABLE IF NOT EXISTS folders (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Catalogo do TikTok Shop, baixado da Central do Vendedor (seller.py). O ID e o
-- do TikTok (unico entre lojas); `shop` e a chave da loja no seller.py.
CREATE TABLE IF NOT EXISTS shop_products (
    id         TEXT PRIMARY KEY,
    shop       TEXT DEFAULT '',
    name       TEXT DEFAULT '',
    image_url  TEXT DEFAULT '',
    price      TEXT DEFAULT '',
    status     INTEGER DEFAULT 0,
    active     INTEGER DEFAULT 1,
    synced_at  TEXT DEFAULT ''
);

-- Qual produto vai no carrinho de cada video, em cada loja. kind='library'
-- vale para tudo que sair daquele video-fonte; kind='output' e a excecao de um
-- produzido. O mesmo video pode ter um produto em cada loja.
CREATE TABLE IF NOT EXISTS product_links (
    kind       TEXT NOT NULL,
    ref_id     TEXT NOT NULL,
    shop       TEXT NOT NULL DEFAULT '',
    product_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id, shop)
);

-- Lojas do TikTok Shop (seller.py): um login na Central do Vendedor cada, com
-- perfil de navegador proprio em seller_browser/<key>.
CREATE TABLE IF NOT EXISTS shops (
    key                TEXT PRIMARY KEY,
    name               TEXT DEFAULT '',
    seller_id          TEXT DEFAULT '',
    code               TEXT DEFAULT '',
    video_url          TEXT DEFAULT '',
    products_synced_at TEXT DEFAULT '',
    last_login_ok      TEXT DEFAULT '',
    created_at         TEXT NOT NULL
);

-- As contas do TikTok vinculadas a cada loja (oficial e de marketing), na
-- ordem em que aparecem na Central.
CREATE TABLE IF NOT EXISTS shop_accounts (
    shop      TEXT NOT NULL,
    handle    TEXT NOT NULL,
    tt_id     TEXT DEFAULT '',
    nickname  TEXT DEFAULT '',
    role      INTEGER DEFAULT 0,
    eligible  INTEGER DEFAULT 1,
    position  INTEGER DEFAULT 0,
    PRIMARY KEY (shop, handle)
);

-- Ajustes soltos do app (valor em JSON): intervalo da fila, pausa, ultima
-- conta usada. Uma tabela, e nao mais um arquivo JSON por recurso.
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id                TEXT PRIMARY KEY,
    platform          TEXT DEFAULT 'tiktok',
    open_id           TEXT DEFAULT '',
    nickname          TEXT DEFAULT '',
    avatar_url        TEXT DEFAULT '',
    access_token_enc  TEXT DEFAULT '',
    refresh_token_enc TEXT DEFAULT '',
    expires_at        TEXT DEFAULT '',
    scopes            TEXT DEFAULT '',
    audited           INTEGER DEFAULT 0,
    created_at        TEXT NOT NULL
);
"""

# Estados de publicacao que contam como "publicado de verdade".
# `publicado` significa publicado **de verdade**: o TikTok so devolve
# PUBLISH_COMPLETE depois que o criador tocou na notificacao e concluiu o post.
PUBLISHED_STATES = ("publicado",)

# Entregue na caixa de entrada, esperando o usuario terminar dentro do TikTok.
# Precisa ser um estado proprio: por muito tempo o app chamou isto de
# "publicado", o que fazia a interface prometer algo que nao tinha acontecido --
# e mandava o usuario procurar no perfil um video que estava numa notificacao.
AWAITING_STATES = ("aguardando",)

PENDING_STATES = ("fila", "enviando", "processando", "agendado")


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_store(db_path):
    """Abre (ou cria) o banco. Chamado uma vez no boot do backend."""
    global _CONN
    with _LOCK:
        _CONN = sqlite3.connect(str(db_path), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        # WAL deixa leitura e escrita concorrerem sem travar uma a outra.
        _CONN.execute("PRAGMA journal_mode=WAL")
        _CONN.execute("PRAGMA synchronous=NORMAL")
        _CONN.executescript(SCHEMA)
        _migrar(_CONN)
        _CONN.commit()
    return _CONN


def _migrar(con):
    """Ajustes de esquema em bancos que ja existem.

    `CREATE TABLE IF NOT EXISTS` cuida das tabelas novas, mas nao acrescenta
    coluna a uma tabela que ja existe -- e este banco esta em uso, com videos
    dentro. Cada passo confere antes de agir, para a funcao poder rodar em todo
    boot sem efeito.
    """
    colunas = {r["name"] for r in con.execute("PRAGMA table_info(outputs)")}
    if "folder_id" not in colunas:
        con.execute("ALTER TABLE outputs ADD COLUMN folder_id TEXT DEFAULT ''")
        con.execute("CREATE INDEX IF NOT EXISTS idx_outputs_folder ON outputs(folder_id)")
    # Publicacao marcada a mao: quem posta o video fora do app (direto no
    # aplicativo do TikTok) precisa de um jeito de dizer que ja publicou.
    if "manual_published_at" not in colunas:
        con.execute("ALTER TABLE outputs ADD COLUMN manual_published_at TEXT DEFAULT ''")
    # Publicacao pelo TikTok Shop (seller.py): a conta de destino e um @ da
    # Central do Vendedor, nao uma linha de `accounts` -- nao ha token dela.
    colunas_pub = {r["name"] for r in con.execute("PRAGMA table_info(publications)")}
    if "target" not in colunas_pub:
        con.execute("ALTER TABLE publications ADD COLUMN target TEXT DEFAULT ''")
    # Varias lojas do TikTok Shop: a publicacao sabe de qual loja e.
    if "shop" not in colunas_pub:
        con.execute("ALTER TABLE publications ADD COLUMN shop TEXT DEFAULT ''")
    colunas_prod = {r["name"] for r in con.execute("PRAGMA table_info(shop_products)")}
    if "shop" not in colunas_prod:
        con.execute("ALTER TABLE shop_products ADD COLUMN shop TEXT DEFAULT ''")
    # A chave de product_links ganhou a loja; SQLite nao troca chave primaria
    # no lugar, entao a tabela e refeita.
    colunas_link = {r["name"] for r in con.execute("PRAGMA table_info(product_links)")}
    if "shop" not in colunas_link:
        con.execute("ALTER TABLE product_links RENAME TO product_links_v1")
        con.execute("""CREATE TABLE product_links (
            kind TEXT NOT NULL, ref_id TEXT NOT NULL, shop TEXT NOT NULL DEFAULT '',
            product_id TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (kind, ref_id, shop))""")
        con.execute("""INSERT INTO product_links (kind, ref_id, shop, product_id, updated_at)
            SELECT l.kind, l.ref_id, COALESCE(p.shop, ''), l.product_id, l.updated_at
            FROM product_links_v1 l LEFT JOIN shop_products p ON p.id = l.product_id""")
        con.execute("DROP TABLE product_links_v1")


def _rows(sql, params=()):
    with _LOCK:
        return [dict(r) for r in _CONN.execute(sql, params).fetchall()]


def _one(sql, params=()):
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _exec(sql, params=()):
    with _LOCK:
        cur = _CONN.execute(sql, params)
        _CONN.commit()
        return cur


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------

def _decode_output(row):
    if not row:
        return None
    out = dict(row)
    try:
        out["hashtags"] = json.loads(out.get("hashtags") or "[]")
    except (ValueError, TypeError):
        out["hashtags"] = []
    out["audio_mode"] = bool(out.get("audio_mode"))
    out["manual_published_at"] = out.get("manual_published_at") or ""
    out["published_manually"] = bool(out["manual_published_at"])
    return out


def add_output(
    file,
    job_id="",
    library_id="",
    phrase="",
    speech="",
    caption="",
    hashtags=None,
    theme="",
    source_name="",
    duration=0.0,
    audio_mode=False,
    created_at=None,
    output_id=None,
):
    oid = output_id or uuid.uuid4().hex
    _exec(
        """INSERT OR REPLACE INTO outputs
           (id, job_id, library_id, file, phrase, speech, caption, hashtags,
            theme, source_name, duration, audio_mode, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            oid,
            job_id or "",
            library_id or "",
            file,
            phrase or "",
            speech or "",
            caption or "",
            json.dumps(cap.normalize_hashtags(hashtags), ensure_ascii=False),
            theme or "",
            source_name or "",
            float(duration or 0),
            1 if audio_mode else 0,
            "pronto",
            created_at or _now(),
        ),
    )
    return get_output(oid)


def get_output(output_id):
    return _decode_output(_one("SELECT * FROM outputs WHERE id = ?", (output_id,)))


def get_output_by_file(file):
    return _decode_output(_one("SELECT * FROM outputs WHERE file = ?", (file,)))


def list_outputs(status=None, library_id=None, job_id=None, search=None,
                 folder_id=None, limit=200, offset=0):
    sql = "SELECT * FROM outputs WHERE 1=1"
    params = []
    # `folder_id=""` e um filtro legitimo -- "sem pasta" e uma secao de verdade,
    # e nao ausencia de filtro. Por isso o teste e contra None, nao contra
    # falsidade: `if folder_id:` deixaria a secao "sem pasta" listar tudo.
    if folder_id is not None:
        sql += " AND folder_id = ?"
        params.append(folder_id)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if library_id:
        sql += " AND library_id = ?"
        params.append(library_id)
    if job_id:
        sql += " AND job_id = ?"
        params.append(job_id)
    if search:
        sql += " AND (phrase LIKE ? OR caption LIKE ? OR theme LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]

    items = [_decode_output(r) for r in _rows(sql, tuple(params))]
    _attach_publications(items)
    return items


def _attach_publications(items):
    """Anexa as publicacoes de cada output em uma consulta so."""
    if not items:
        return items
    _attach_product(items)
    ids = [i["id"] for i in items]
    marks = ",".join("?" * len(ids))
    pubs = _rows(
        f"SELECT * FROM publications WHERE output_id IN ({marks}) ORDER BY created_at DESC",
        tuple(ids),
    )
    by_output = {}
    for p in pubs:
        try:
            p["product_ids"] = json.loads(p.get("product_ids") or "[]")
        except (ValueError, TypeError):
            p["product_ids"] = []
        by_output.setdefault(p["output_id"], []).append(p)
    for item in items:
        item["publications"] = by_output.get(item["id"], [])
        # Marcar a mao vale tanto quanto o TikTok confirmar: o video foi ao ar
        # do mesmo jeito, so que por fora do app.
        item["published"] = bool(item.get("manual_published_at")) or any(
            p["state"] in PUBLISHED_STATES for p in item["publications"]
        )
        item["awaiting"] = not item["published"] and any(
            p["state"] in AWAITING_STATES for p in item["publications"]
        )
    return items


# Campos que `update_output` aceita. A lista existe para uma rota HTTP nao poder
# escrever em qualquer coluna a partir de um JSON do cliente.
#
# O preco dela e silencioso: um campo esquecido aqui e descartado sem erro, e
# quem chamou acha que gravou. Ja aconteceu tres vezes neste projeto -- por isso
# `update_output` agora recusa campo desconhecido em vez de ignora-lo.
UPDATABLE_OUTPUT_FIELDS = {
    "caption", "hashtags", "phrase", "status", "theme", "folder_id",
    "library_id", "manual_published_at",
}


def update_output(output_id, **fields):
    # Campo desconhecido levanta erro em vez de sumir. Filtrar em silencio
    # transforma um erro de programacao numa gravacao que nao aconteceu, e o
    # sintoma aparece longe da causa -- foi assim que 45 religacoes de
    # `library_id` foram reportadas como feitas sem terem sido.
    desconhecidos = set(fields) - UPDATABLE_OUTPUT_FIELDS
    if desconhecidos:
        raise ValueError(
            f"update_output: campo(s) que nao podem ser gravados: "
            f"{', '.join(sorted(desconhecidos))}"
        )

    sets, params = [], []
    for key, value in fields.items():
        if key not in UPDATABLE_OUTPUT_FIELDS:
            continue
        if key == "hashtags":
            # Ultima barreira antes do disco: o limite vale para qualquer caller.
            value = json.dumps(cap.normalize_hashtags(value), ensure_ascii=False)
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return get_output(output_id)
    params.append(output_id)
    _exec(f"UPDATE outputs SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return get_output(output_id)


def delete_output(output_id):
    item = get_output(output_id)
    _exec("DELETE FROM publications WHERE output_id = ?", (output_id,))
    _exec("DELETE FROM outputs WHERE id = ?", (output_id,))
    return item


def outputs_for_job(job_id):
    items = [
        _decode_output(r)
        for r in _rows(
            "SELECT * FROM outputs WHERE job_id = ? ORDER BY created_at ASC", (job_id,)
        )
    ]
    return _attach_publications(items)


# ---------------------------------------------------------------------------
# metricas
# ---------------------------------------------------------------------------

def _count(sql, params=()):
    with _LOCK:
        row = _CONN.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def metrics():
    """Os numeros que o painel mostra.

    'publicados' conta outputs distintos de proposito: um video postado em duas
    contas e um video publicado, nao dois.
    """
    marks_pub = ",".join("?" * len(PUBLISHED_STATES))
    marks_pend = ",".join("?" * len(PENDING_STATES))

    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    month = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    # Um video publicado pelo app E marcado a mao continua sendo um video.
    published = _count(
        f"""SELECT COUNT(*) FROM outputs WHERE manual_published_at != ''
               OR id IN (SELECT output_id FROM publications
                         WHERE state IN ({marks_pub}))""",
        PUBLISHED_STATES,
    )
    total = _count("SELECT COUNT(*) FROM outputs")
    return {
        "total_produced": total,
        "total_published": published,
        "not_published": max(total - published, 0),
        "pending": _count(
            f"SELECT COUNT(*) FROM publications WHERE state IN ({marks_pend})",
            PENDING_STATES,
        ),
        "awaiting": _count(
            f"SELECT COUNT(DISTINCT output_id) FROM publications WHERE state IN "
            f"({','.join('?' * len(AWAITING_STATES))})",
            AWAITING_STATES,
        ),
        "failed": _count("SELECT COUNT(*) FROM publications WHERE state = 'erro'"),
        "produced_7d": _count("SELECT COUNT(*) FROM outputs WHERE created_at >= ?", (week,)),
        "produced_30d": _count("SELECT COUNT(*) FROM outputs WHERE created_at >= ?", (month,)),
        "published_7d": _count(
            f"""SELECT COUNT(*) FROM outputs WHERE manual_published_at >= ?
                   OR id IN (SELECT output_id FROM publications
                             WHERE state IN ({marks_pub}) AND published_at >= ?)""",
            (week,) + PUBLISHED_STATES + (week,),
        ),
        "accounts": _count("SELECT COUNT(*) FROM accounts"),
    }


def counts_by_library():
    """{library_id: {"produced": n, "published": n}} para os cards da Biblioteca."""
    marks = ",".join("?" * len(PUBLISHED_STATES))
    out = {}
    for row in _rows(
        "SELECT library_id, COUNT(*) AS n FROM outputs "
        "WHERE library_id != '' GROUP BY library_id"
    ):
        out[row["library_id"]] = {"produced": int(row["n"]), "published": 0}
    for row in _rows(
        f"SELECT o.library_id AS library_id, COUNT(DISTINCT p.output_id) AS n "
        f"FROM publications p JOIN outputs o ON o.id = p.output_id "
        f"WHERE p.state IN ({marks}) AND o.library_id != '' GROUP BY o.library_id",
        PUBLISHED_STATES,
    ):
        out.setdefault(row["library_id"], {"produced": 0, "published": 0})
        out[row["library_id"]]["published"] = int(row["n"])
    return out


# ---------------------------------------------------------------------------
# publicacoes
# ---------------------------------------------------------------------------

def add_publication(
    output_id,
    platform="tiktok",
    account_id="",
    mode="draft",
    privacy="",
    product_mode="nenhum",
    product_ids=None,
    state="fila",
    scheduled_for="",
    target="",
    shop="",
):
    pid = uuid.uuid4().hex
    _exec(
        """INSERT INTO publications
           (id, output_id, platform, account_id, mode, privacy, product_mode,
            product_ids, state, scheduled_for, created_at, target, shop)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pid,
            output_id,
            platform,
            account_id,
            mode,
            privacy,
            product_mode,
            json.dumps(list(product_ids or []), ensure_ascii=False),
            state,
            scheduled_for,
            _now(),
            target or "",
            shop or "",
        ),
    )
    return get_publication(pid)


def get_publication(pub_id):
    row = _one("SELECT * FROM publications WHERE id = ?", (pub_id,))
    if row:
        try:
            row["product_ids"] = json.loads(row.get("product_ids") or "[]")
        except (ValueError, TypeError):
            row["product_ids"] = []
    return row


UPDATABLE_PUB_FIELDS = {
    "publish_id", "state", "error", "published_at", "post_url",
    "privacy", "mode", "product_mode", "scheduled_for", "target", "product_ids",
    "shop",
}


def update_publication(pub_id, **fields):
    sets, params = [], []
    for key, value in fields.items():
        if key not in UPDATABLE_PUB_FIELDS:
            continue
        if key == "product_ids":
            value = json.dumps(list(value or []), ensure_ascii=False)
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return get_publication(pub_id)
    params.append(pub_id)
    _exec(f"UPDATE publications SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return get_publication(pub_id)


def list_publications(state=None, limit=200):
    sql = "SELECT * FROM publications"
    params = []
    if state:
        sql += " WHERE state = ?"
        params.append(state)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    rows = _rows(sql, tuple(params))
    for r in rows:
        try:
            r["product_ids"] = json.loads(r.get("product_ids") or "[]")
        except (ValueError, TypeError):
            r["product_ids"] = []
    return rows


def shop_publications(states=None, limit=300):
    """Publicacoes do TikTok Shop, da mais antiga para a mais nova."""
    sql = "SELECT * FROM publications WHERE platform = 'tiktok_shop'"
    params = []
    if states:
        sql += f" AND state IN ({','.join('?' * len(states))})"
        params += list(states)
    sql += " ORDER BY created_at ASC LIMIT ?"
    params.append(int(limit))
    rows = _rows(sql, tuple(params))
    for r in rows:
        try:
            r["product_ids"] = json.loads(r.get("product_ids") or "[]")
        except (ValueError, TypeError):
            r["product_ids"] = []
    return rows


def shop_queue():
    """O que ainda falta publicar pelo TikTok Shop, na ordem de chegada."""
    return shop_publications(states=("fila",))


def shop_history(limit=100):
    """As mais recentes primeiro, para a tela da fila."""
    rows = _rows(
        "SELECT * FROM (SELECT * FROM publications WHERE platform = 'tiktok_shop' "
        "ORDER BY created_at DESC LIMIT ?) ORDER BY created_at ASC",
        (int(limit),),
    )
    for r in rows:
        try:
            r["product_ids"] = json.loads(r.get("product_ids") or "[]")
        except (ValueError, TypeError):
            r["product_ids"] = []
    return rows


# ---------------------------------------------------------------------------
# produtos do TikTok Shop e o vinculo com os videos
# ---------------------------------------------------------------------------

def save_shop_products(produtos, shop):
    """Grava o catalogo baixado de uma loja. O que sumiu do TikTok fica, mas
    inativo: um video ja vinculado a ele continua mostrando o nome."""
    agora = _now()
    with _LOCK:
        _CONN.execute("UPDATE shop_products SET active = 0 WHERE shop = ?", (shop,))
        for p in produtos:
            _CONN.execute(
                """INSERT INTO shop_products (id, shop, name, image_url, price, status, active, synced_at)
                   VALUES (?,?,?,?,?,?,1,?)
                   ON CONFLICT(id) DO UPDATE SET shop=excluded.shop, name=excluded.name,
                     image_url=excluded.image_url, price=excluded.price,
                     status=excluded.status, active=1, synced_at=excluded.synced_at""",
                (str(p["id"]), shop, p.get("name", "")[:300], p.get("image_url", "")[:1000],
                 p.get("price", "")[:60], int(p.get("status") or 0), agora),
            )
        _CONN.commit()


def upsert_shop_product(product_id, name, shop):
    """Produto visto na hora de publicar, antes de qualquer sincronizacao."""
    _exec(
        """INSERT INTO shop_products (id, shop, name, synced_at) VALUES (?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name = CASE WHEN shop_products.name = ''
             THEN excluded.name ELSE shop_products.name END""",
        (str(product_id), shop, (name or "")[:300], _now()),
    )


def list_shop_products(shop=None, include_inactive=False):
    sql, params = "SELECT * FROM shop_products WHERE 1=1", []
    if shop:
        sql += " AND shop = ?"
        params.append(shop)
    if not include_inactive:
        sql += " AND active = 1"
    rows = _rows(sql + " ORDER BY name COLLATE NOCASE", tuple(params))
    contagem = {}
    for r in _rows("SELECT product_id, COUNT(*) AS n FROM product_links GROUP BY product_id"):
        contagem[r["product_id"]] = int(r["n"])
    for r in rows:
        r["links"] = contagem.get(r["id"], 0)
        r["active"] = bool(r["active"])
    return rows


def count_shop_products():
    return {r["shop"]: int(r["n"]) for r in _rows(
        "SELECT shop, COUNT(*) AS n FROM shop_products WHERE active = 1 GROUP BY shop")}


def get_shop_product(product_id):
    return _one("SELECT * FROM shop_products WHERE id = ?", (str(product_id),))


def set_product_link(kind, ref_id, shop, product_id):
    if kind not in ("library", "output"):
        raise ValueError("kind invalido")
    if product_id:
        _exec(
            """INSERT INTO product_links (kind, ref_id, shop, product_id, updated_at) VALUES (?,?,?,?,?)
               ON CONFLICT(kind, ref_id, shop) DO UPDATE SET product_id=excluded.product_id,
                 updated_at=excluded.updated_at""",
            (kind, ref_id, shop, str(product_id), _now()),
        )
    else:
        _exec("DELETE FROM product_links WHERE kind = ? AND ref_id = ? AND shop = ?",
              (kind, ref_id, shop))


def product_links(kind):
    """{ref_id: {loja: product_id}}"""
    out = {}
    for r in _rows("SELECT ref_id, shop, product_id FROM product_links WHERE kind = ?", (kind,)):
        out.setdefault(r["ref_id"], {})[r["shop"]] = r["product_id"]
    return out


def product_for_output(output, shop):
    """O produto do video nesta loja: o dele mesmo, senao o do video-fonte."""
    if not output or not shop:
        return ""
    r = _one("SELECT product_id FROM product_links WHERE kind='output' AND ref_id=? AND shop=?",
             (output["id"], shop))
    if r:
        return r["product_id"]
    if output.get("library_id"):
        r = _one("SELECT product_id FROM product_links WHERE kind='library' AND ref_id=? AND shop=?",
                 (output["library_id"], shop))
        if r:
            return r["product_id"]
    return ""


def _attach_product(items):
    """shop_products = {loja: {"own": vinculo do proprio video, "resolved": o que vale}}."""
    por_output = product_links("output")
    por_fonte = product_links("library")
    for item in items:
        proprios = por_output.get(item["id"], {})
        da_fonte = por_fonte.get(item.get("library_id") or "", {})
        item["shop_products"] = {
            loja: {"own": proprios.get(loja, ""), "resolved": proprios.get(loja) or da_fonte.get(loja, "")}
            for loja in set(proprios) | set(da_fonte)
        }


def assign_shop_to_orphans(shop):
    """Da versao de uma loja so: o que nao tinha loja passa a ser desta."""
    with _LOCK:
        _CONN.execute("UPDATE shop_products SET shop = ? WHERE shop = ''", (shop,))
        _CONN.execute("UPDATE product_links SET shop = ? WHERE shop = ''", (shop,))
        _CONN.execute("UPDATE publications SET shop = ? WHERE platform = 'tiktok_shop' AND shop = ''",
                      (shop,))
        _CONN.commit()


def forget_shop(shop):
    """Loja removida: some o catalogo e os vinculos dela (o historico fica)."""
    with _LOCK:
        _CONN.execute("DELETE FROM shop_products WHERE shop = ?", (shop,))
        _CONN.execute("DELETE FROM product_links WHERE shop = ?", (shop,))
        _CONN.commit()


# ---------------------------------------------------------------------------
# ajustes, lojas e contas do TikTok Shop
# ---------------------------------------------------------------------------

def setting_get(key, default=None):
    r = _one("SELECT value FROM app_settings WHERE key = ?", (key,))
    if not r:
        return default
    try:
        return json.loads(r["value"])
    except (ValueError, TypeError):
        return default


def setting_set(**valores):
    with _LOCK:
        for k, v in valores.items():
            _CONN.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, json.dumps(v, ensure_ascii=False)),
            )
        _CONN.commit()


SHOP_FIELDS = ("name", "seller_id", "code", "video_url", "products_synced_at", "last_login_ok", "created_at")


def list_shops():
    return _rows("SELECT * FROM shops ORDER BY created_at, key")


def get_shop(key):
    return _one("SELECT * FROM shops WHERE key = ?", (key,))


def upsert_shop(key, **fields):
    desconhecidos = set(fields) - set(SHOP_FIELDS)
    if desconhecidos:
        raise ValueError(f"upsert_shop: campo(s) desconhecido(s): {', '.join(sorted(desconhecidos))}")
    with _LOCK:
        _CONN.execute("INSERT OR IGNORE INTO shops (key, created_at) VALUES (?, ?)",
                      (key, fields.get("created_at") or _now()))
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            _CONN.execute(f"UPDATE shops SET {sets} WHERE key = ?", (*fields.values(), key))
        _CONN.commit()
    return get_shop(key)


def delete_shop(key):
    with _LOCK:
        _CONN.execute("DELETE FROM shop_accounts WHERE shop = ?", (key,))
        _CONN.execute("DELETE FROM shops WHERE key = ?", (key,))
        _CONN.commit()


def list_shop_accounts(shop):
    rows = _rows("SELECT * FROM shop_accounts WHERE shop = ? ORDER BY position, handle", (shop,))
    for r in rows:
        r["eligible"] = bool(r["eligible"])
    return rows


def set_shop_accounts(shop, contas):
    """Grava a lista inteira de contas da loja, na ordem dada."""
    with _LOCK:
        _CONN.execute("DELETE FROM shop_accounts WHERE shop = ?", (shop,))
        for i, c in enumerate(contas):
            _CONN.execute(
                """INSERT INTO shop_accounts (shop, handle, tt_id, nickname, role, eligible, position)
                   VALUES (?,?,?,?,?,?,?)""",
                (shop, c["handle"], c.get("id", "") or c.get("tt_id", ""), c.get("nickname", ""),
                 int(c.get("role") or 0), 1 if c.get("eligible", True) else 0, i),
            )
        _CONN.commit()


# ---------------------------------------------------------------------------
# migracao do localStorage
# ---------------------------------------------------------------------------

def import_history(entries, existing_files):
    """Importa o historico que vivia no localStorage do React.

    Roda uma vez. So aceita entradas cujo arquivo ainda existe em outputs/, e
    ignora as que ja foram importadas (chave: o nome do arquivo).
    """
    imported = skipped = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("meta") or {}
        for result in entry.get("results") or []:
            if not isinstance(result, dict):
                continue
            file = str(result.get("file") or "").strip()
            if not file or file not in existing_files:
                skipped += 1
                continue
            if get_output_by_file(file):
                skipped += 1
                continue
            add_output(
                file=file,
                job_id=str(entry.get("id") or ""),
                library_id=str(meta.get("libraryId") or ""),
                phrase=str(result.get("phrase") or ""),
                speech=str(result.get("speech") or ""),
                theme=str(meta.get("theme") or ""),
                source_name=str(meta.get("sourceName") or ""),
                audio_mode=bool(meta.get("audioEnabled")),
                created_at=str(entry.get("date") or _now()),
            )
            imported += 1
    return {"imported": imported, "skipped": skipped}


# ---------------------------------------------------------------------------
# accounts (contas de plataforma conectadas)
# ---------------------------------------------------------------------------
# Os tokens chegam aqui ja cifrados: quem cifra e o modulo que fala com a
# plataforma. O store nunca ve token em texto puro, e por isso nao ha risco de
# um SELECT * cair num log com o segredo dentro.

# Campos que a UI pode ver. `access_token_enc` e `refresh_token_enc` ficam de
# fora de proposito -- eles nunca sao serializados para o frontend.
PUBLIC_ACCOUNT_FIELDS = (
    "id", "platform", "open_id", "nickname", "avatar_url",
    "expires_at", "scopes", "audited", "created_at",
)


def public_account(row):
    """Versao da conta segura para atravessar HTTP ate o React."""
    if not row:
        return None
    out = {k: row.get(k) for k in PUBLIC_ACCOUNT_FIELDS}
    out["audited"] = bool(out.get("audited"))
    out["connected"] = bool(row.get("access_token_enc"))
    return out


def set_account_avatar(account_id, avatar_url):
    """Atualiza so a foto. Ela vence sozinha, sem que a conta mude em nada."""
    _exec("UPDATE accounts SET avatar_url = ? WHERE id = ?", (avatar_url, account_id))
    return get_account(account_id)


def upsert_account(
    platform,
    open_id,
    nickname="",
    avatar_url="",
    access_token_enc="",
    refresh_token_enc="",
    expires_at="",
    scopes="",
):
    """Grava a conta. Reconectar a mesma conta atualiza, nao duplica.

    A chave e (platform, open_id): o open_id e o identificador estavel que o
    TikTok devolve. Reconectar por qualquer motivo -- token expirado, escopo
    novo, usuario clicou de novo -- tem que reaproveitar a linha, senao o
    historico de publicacoes aponta para uma conta orfa.
    """
    existing = _one(
        "SELECT * FROM accounts WHERE platform = ? AND open_id = ?",
        (platform, open_id),
    )
    if existing:
        _exec(
            """UPDATE accounts SET nickname = ?, avatar_url = ?,
                   access_token_enc = ?, refresh_token_enc = ?,
                   expires_at = ?, scopes = ?
               WHERE id = ?""",
            (nickname, avatar_url, access_token_enc, refresh_token_enc,
             expires_at, scopes, existing["id"]),
        )
        return get_account(existing["id"])

    account_id = uuid.uuid4().hex[:12]
    _exec(
        """INSERT INTO accounts
               (id, platform, open_id, nickname, avatar_url, access_token_enc,
                refresh_token_enc, expires_at, scopes, audited, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (account_id, platform, open_id, nickname, avatar_url, access_token_enc,
         refresh_token_enc, expires_at, scopes, _now()),
    )
    return get_account(account_id)


def get_account(account_id):
    return _one("SELECT * FROM accounts WHERE id = ?", (account_id,))


def active_account(platform="tiktok"):
    """A conta que o app usa hoje.

    O modelo suporta varias contas (a tabela tem id proprio), mas a fase 4
    trabalha com uma so. Pegar a mais recente com token evita que uma conta
    desconectada, cuja linha ficou para tras, seja escolhida.
    """
    return _one(
        """SELECT * FROM accounts
           WHERE platform = ? AND access_token_enc != ''
           ORDER BY created_at DESC LIMIT 1""",
        (platform,),
    )


def list_accounts(platform=None):
    if platform:
        return _rows(
            "SELECT * FROM accounts WHERE platform = ? ORDER BY created_at DESC",
            (platform,),
        )
    return _rows("SELECT * FROM accounts ORDER BY created_at DESC")


UPDATABLE_ACCOUNT_FIELDS = (
    "nickname", "avatar_url", "access_token_enc", "refresh_token_enc",
    "expires_at", "scopes", "audited",
)


def update_account(account_id, **fields):
    sets, params = [], []
    for key, value in fields.items():
        if key not in UPDATABLE_ACCOUNT_FIELDS:
            continue
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return get_account(account_id)
    params.append(account_id)
    _exec(f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?", tuple(params))
    return get_account(account_id)


def delete_account(account_id):
    """Desconecta.

    Apaga a linha inteira em vez de so limpar os tokens: manter open_id e
    apelido de uma conta desconectada e guardar dado pessoal sem finalidade --
    e a politica de privacidade publicada promete o contrario. As publicacoes
    ja feitas guardam o `account_id` como texto, entao o historico sobrevive.
    """
    item = get_account(account_id)
    _exec("DELETE FROM accounts WHERE id = ?", (account_id,))
    return item


# ---------------------------------------------------------------------------
# pastas
# ---------------------------------------------------------------------------
# Planas, sem aninhamento. Pasta dentro de pasta exige arvore na interface,
# mover em cascata e decidir o que acontece com o conteudo ao apagar a mae --
# complexidade que so se paga com muitos itens. Com dezenas, uma lista basta.

def add_folder(name):
    nome = (name or "").strip()
    if not nome:
        raise ValueError("nome vazio")
    fid = uuid.uuid4().hex[:12]
    _exec(
        "INSERT INTO folders (id, name, created_at) VALUES (?, ?, ?)",
        (fid, nome[:60], _now()),
    )
    return get_folder(fid)


def get_folder(folder_id):
    return _one("SELECT * FROM folders WHERE id = ?", (folder_id,))


def list_folders():
    return _rows("SELECT * FROM folders ORDER BY name COLLATE NOCASE ASC")


def rename_folder(folder_id, name):
    nome = (name or "").strip()
    if not nome:
        raise ValueError("nome vazio")
    _exec("UPDATE folders SET name = ? WHERE id = ?", (nome[:60], folder_id))
    return get_folder(folder_id)


def delete_folder(folder_id):
    """Apaga a pasta, nao o conteudo.

    Os itens voltam para "sem pasta". Apagar videos junto seria uma perda
    irreversivel disparada por uma acao que parece organizacional.
    """
    item = get_folder(folder_id)
    _exec("UPDATE outputs SET folder_id = '' WHERE folder_id = ?", (folder_id,))
    _exec("DELETE FROM folders WHERE id = ?", (folder_id,))
    return item


def count_outputs_by_folder():
    """{folder_id: quantidade} para a contagem na barra lateral."""
    return {
        r["folder_id"]: int(r["n"])
        for r in _rows(
            "SELECT folder_id, COUNT(*) AS n FROM outputs "
            "WHERE folder_id != '' GROUP BY folder_id"
        )
    }
