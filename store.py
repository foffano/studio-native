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
PUBLISHED_STATES = ("publicado",)
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
        _CONN.commit()
    return _CONN


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


def list_outputs(status=None, library_id=None, job_id=None, search=None, limit=200, offset=0):
    sql = "SELECT * FROM outputs WHERE 1=1"
    params = []
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
        item["published"] = any(
            p["state"] in PUBLISHED_STATES for p in item["publications"]
        )
    return items


UPDATABLE_OUTPUT_FIELDS = {"caption", "hashtags", "phrase", "status", "theme"}


def update_output(output_id, **fields):
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

    published = _count(
        f"SELECT COUNT(DISTINCT output_id) FROM publications WHERE state IN ({marks_pub})",
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
        "failed": _count("SELECT COUNT(*) FROM publications WHERE state = 'erro'"),
        "produced_7d": _count("SELECT COUNT(*) FROM outputs WHERE created_at >= ?", (week,)),
        "produced_30d": _count("SELECT COUNT(*) FROM outputs WHERE created_at >= ?", (month,)),
        "published_7d": _count(
            f"SELECT COUNT(DISTINCT output_id) FROM publications "
            f"WHERE state IN ({marks_pub}) AND published_at >= ?",
            PUBLISHED_STATES + (week,),
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
):
    pid = uuid.uuid4().hex
    _exec(
        """INSERT INTO publications
           (id, output_id, platform, account_id, mode, privacy, product_mode,
            product_ids, state, scheduled_for, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
    "privacy", "mode", "product_mode", "scheduled_for",
}


def update_publication(pub_id, **fields):
    sets, params = [], []
    for key, value in fields.items():
        if key not in UPDATABLE_PUB_FIELDS:
            continue
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
