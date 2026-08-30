import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import queue
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory,
    session,
)
from PIL import Image, ImageDraw, ImageFont

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

import auth
import captions as cap
import secretbox
import store
import tiktok

# ---------------------------------------------------------------------------
# Resolucao de caminhos (suporta execucao normal e empacotada com PyInstaller).
# ---------------------------------------------------------------------------
IS_FROZEN = getattr(sys, "frozen", False)


def resource_path(rel):
    """Caminho de um recurso empacotado (assets read-only).

    Sob PyInstaller os assets ficam em sys._MEIPASS; em dev, ao lado do app.py.
    """
    if IS_FROZEN:
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base = Path(__file__).resolve().parent
    return base / rel


def user_data_dir():
    """Diretorio gravavel por usuario (config, uploads, outputs)."""
    if os.name == "nt":
        root = os.getenv("APPDATA") or str(Path.home())
    elif sys.platform == "darwin":
        root = str(Path.home() / "Library" / "Application Support")
    else:
        root = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(root) / "StudioNative"
    d.mkdir(parents=True, exist_ok=True)
    return d


BASE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = resource_path(".")
FONTS_DIR = resource_path("fonts")

USER_DATA_DIR = user_data_dir()
CONFIG_PATH = USER_DATA_DIR / "config.json"
UPLOAD_DIR = USER_DATA_DIR / "uploads"
OUTPUT_DIR = USER_DATA_DIR / "outputs"

# Front construido (Vite). Empacotado como "webui" no bundle; em dev fica em
# desktop/dist. Serve para o modo navegador -- no Electron o renderer e
# carregado de file:// e nao passa por aqui.
WEB_DIR = resource_path("webui")
if not WEB_DIR.exists():
    WEB_DIR = Path(__file__).resolve().parent / "desktop" / "dist"
LIBRARY_DIR = USER_DATA_DIR / "library"
LIBRARY_STAGING = USER_DATA_DIR / "library_staging"
LIBRARY_META_PATH = USER_DATA_DIR / "library.json"
STUDIO_DB_PATH = USER_DATA_DIR / "studio.db"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
LIBRARY_STAGING.mkdir(parents=True, exist_ok=True)

# Carrega .env (apenas em dev / compatibilidade) sem sobrescrever o ambiente.
load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

# Estimativa de ritmo de fala (palavras por segundo) para dimensionar a narracao.
WORDS_PER_SECOND = 2.5

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

# Fonte arredondada empacotada no projeto (com instancia "SemiBold" da fonte variavel)
ROUNDED_FONT_PATH = FONTS_DIR / "Quicksand.ttf"
ROUNDED_FONT_VARIATION = "SemiBold"

# ---------------------------------------------------------------------------
# Configuracoes / chaves de API. Precedencia: config.json (UI) > env/.env > default.
# Sao guardadas em globals mutaveis em runtime (atualizadas pela tela de Ajustes).
# ---------------------------------------------------------------------------
SETTINGS_DEFAULTS = {
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_MODEL": "openai/gpt-4o-mini",
    "ELEVENLABS_API_KEY": "",
    "ELEVENLABS_MODEL": "eleven_multilingual_v2",
    "MAX_HEIGHT": 1080,
    "voices": [],
    # Hash scrypt da senha do admin. Vazio = app ainda nao configurado, e a
    # primeira coisa que a interface pede e criar uma senha.
    "ADMIN_PASSWORD_HASH": "",
    # Chave que assina o cookie de sessao. Persistida para os logins
    # sobreviverem a um reinicio do servico.
    "SESSION_SECRET": "",
}
SECRET_KEYS = {"OPENROUTER_API_KEY", "ELEVENLABS_API_KEY"}

SETTINGS = dict(SETTINGS_DEFAULTS)

# Globals derivados (lidos pelas funcoes em runtime).
OPENROUTER_API_KEY = ""
OPENROUTER_MODEL = SETTINGS_DEFAULTS["OPENROUTER_MODEL"]
ELEVENLABS_API_KEY = ""
ELEVENLABS_MODEL = SETTINGS_DEFAULTS["ELEVENLABS_MODEL"]
MAX_HEIGHT = SETTINGS_DEFAULTS["MAX_HEIGHT"]
VOICES = []


def normalize_voices(items):
    """Valida/normaliza a lista de vozes salvas (cada voz: nome + voice_id +
    parametros avancados opcionais)."""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        vid = str(it.get("voice_id") or "").strip()
        name = str(it.get("name") or "").strip()
        if not vid or not name:
            continue
        voice = {
            "id": str(it.get("id") or uuid.uuid4().hex),
            "name": name,
            "voice_id": vid,
        }
        model_id = str(it.get("model_id") or "").strip()
        if model_id:
            voice["model_id"] = model_id
        for f in ("stability", "similarity"):
            val = it.get(f)
            if val is not None and str(val).strip() != "":
                try:
                    voice[f] = max(0.0, min(1.0, float(val)))
                except (TypeError, ValueError):
                    pass
        out.append(voice)
    return out


def _load_config_file():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_config_file(data):
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def apply_settings():
    """Recalcula os globals derivados a partir de SETTINGS."""
    global OPENROUTER_API_KEY, OPENROUTER_MODEL
    global ELEVENLABS_API_KEY, ELEVENLABS_MODEL, MAX_HEIGHT, VOICES
    OPENROUTER_API_KEY = str(SETTINGS.get("OPENROUTER_API_KEY", "")).strip()
    OPENROUTER_MODEL = (
        str(SETTINGS.get("OPENROUTER_MODEL") or "").strip()
        or SETTINGS_DEFAULTS["OPENROUTER_MODEL"]
    )
    ELEVENLABS_API_KEY = str(SETTINGS.get("ELEVENLABS_API_KEY", "")).strip()
    ELEVENLABS_MODEL = (
        str(SETTINGS.get("ELEVENLABS_MODEL") or "").strip()
        or SETTINGS_DEFAULTS["ELEVENLABS_MODEL"]
    )
    try:
        MAX_HEIGHT = int(SETTINGS.get("MAX_HEIGHT", 1080))
    except (TypeError, ValueError):
        MAX_HEIGHT = 1080
    VOICES = normalize_voices(SETTINGS.get("voices") or [])
    SETTINGS["voices"] = VOICES


def init_settings():
    """Mescla defaults < env/.env < config.json e aplica nos globals."""
    global SETTINGS
    merged = dict(SETTINGS_DEFAULTS)
    for k in SETTINGS_DEFAULTS:
        envv = os.getenv(k)
        if envv is not None and str(envv).strip() != "":
            merged[k] = envv
    for k, v in _load_config_file().items():
        if k in SETTINGS_DEFAULTS and str(v).strip() != "":
            merged[k] = v
    SETTINGS = merged
    apply_settings()


init_settings()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB

def _corrigir_esquema(wsgi_app):
    """Faz o Flask saber que o pedido chegou por HTTPS.

    Atras do tunel, a Cloudflare entrega ao Flask em HTTP puro no loopback --
    entao `request.host_url` diria "http://native.toffa.com.br". O
    `redirect_uri` do OAuth sairia com o esquema errado, e o TikTok, que compara
    byte a byte com o que esta registrado, recusaria a troca com um erro que nao
    menciona esquema nenhum.

    **O `ProxyFix` do Werkzeug nao resolve aqui**: ele procura
    `X-Forwarded-Proto`, e o cloudflared nao envia esse cabecalho. Quem carrega
    a informacao e o `CF-Visitor`, no formato `{"scheme":"https"}`.

    So confiamos no cabecalho quando a conexao vem do loopback, que e por onde o
    tunel entrega; de qualquer outra origem, ele e ignorado.
    """
    def middleware(environ, start_response):
        remoto = environ.get("REMOTE_ADDR", "")
        visitor = environ.get("HTTP_CF_VISITOR", "")
        if remoto in ("127.0.0.1", "::1") and visitor:
            try:
                esquema = json.loads(visitor).get("scheme")
            except (ValueError, AttributeError):
                esquema = None
            if esquema in ("http", "https"):
                environ["wsgi.url_scheme"] = esquema
        return wsgi_app(environ, start_response)

    return middleware


app.wsgi_app = _corrigir_esquema(app.wsgi_app)

app.secret_key = auth.obter_secret_key(SETTINGS, _save_config_file)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Secure fica desligado por padrao porque o app tambem e servido em
    # http://127.0.0.1 -- com a flag ligada, o navegador nao guardaria o cookie
    # ali e o login local nunca funcionaria. O trafego pelo tunel e HTTPS de
    # ponta a ponta de qualquer forma; a flag so impediria o navegador de mandar
    # o cookie por http, e o unico http em jogo e o loopback. Ligue
    # STUDIO_COOKIE_SECURE=1 se um dia servir por http em IP de rede.
    SESSION_COOKIE_SECURE=os.getenv("STUDIO_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# Origens que podem falar com a API de outro endereco. O `*` que existia aqui
# era justificado por "o servidor so escuta em 127.0.0.1" -- premissa que morre
# no instante em que o tunel sobe. Servido pelo proprio Flask, o front usa a
# mesma origem e nao precisa de CORS nenhum; a lista existe so para o Electron e
# o Vite em desenvolvimento.
ORIGENS_PERMITIDAS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
}


@app.after_request
def _add_cors_headers(resp):
    origem = request.headers.get("Origin")
    if origem in ORIGENS_PERMITIDAS:
        resp.headers["Access-Control-Allow-Origin"] = origem
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PATCH, DELETE, OPTIONS"
        )
        resp.headers["Vary"] = "Origin"
    return resp


# ---------------------------------------------------------------------------
# Guarda de autenticacao
# ---------------------------------------------------------------------------
# Uma lista de excecoes, e nao um decorador por rota. Sao 34 rotas: esquecer o
# decorador numa delas seria facil, silencioso, e a rota esquecida provavelmente
# seria uma das que servem arquivos de video -- que nao parecem sensiveis e sao.

PUBLICAS = {
    "/api/health",          # o tunel e o Electron checam antes do login
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/setup",
    "/favicon.ico",
    "/",                    # a casca do front, para a tela de login existir
}


def _rota_publica(caminho):
    if caminho in PUBLICAS:
        return True
    # Os assets do front nao carregam segredo: sao o JS e o CSS que desenham a
    # propria tela de login.
    return caminho.startswith("/assets/")


def senha_configurada():
    return bool(SETTINGS.get("ADMIN_PASSWORD_HASH"))


def _logado():
    return bool(session.get("admin"))


@app.before_request
def _exigir_login():
    if request.method == "OPTIONS" or _rota_publica(request.path):
        return None
    if not senha_configurada():
        return jsonify({"error": "sem_senha", "message": "Defina uma senha de acesso."}), 401
    if not _logado():
        return jsonify({"error": "nao_autenticado"}), 401
    return None


@app.route("/api/auth/status", methods=["GET"])
def api_auth_status():
    return jsonify(
        {
            "senha_configurada": senha_configurada(),
            "autenticado": _logado(),
        }
    )


@app.route("/api/auth/setup", methods=["POST"])
def api_auth_setup():
    """Cria a senha na primeira execucao.

    So funciona enquanto nao existe senha -- depois disso a rota se fecha
    sozinha, senao seria uma porta para trocar a senha sem saber a atual.
    """
    if senha_configurada():
        return jsonify({"error": "Ja existe uma senha definida."}), 409

    senha = str((request.get_json(silent=True) or {}).get("senha") or "")
    problema = auth.forca_da_senha(senha)
    if problema:
        return jsonify({"error": problema}), 400

    SETTINGS["ADMIN_PASSWORD_HASH"] = auth.gerar_hash(senha)
    _save_config_file(SETTINGS)
    session.permanent = True
    session["admin"] = True
    return jsonify({"ok": True})


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    ip = auth.ip_do_pedido(request)
    espera = auth.bloqueado_ate(ip)
    if espera:
        return jsonify({
            "error": f"Tentativas demais. Tente de novo em {espera}s.",
            "espera": espera,
        }), 429

    senha = str((request.get_json(silent=True) or {}).get("senha") or "")
    if not auth.conferir_senha(senha, SETTINGS.get("ADMIN_PASSWORD_HASH")):
        auth.registrar_falha(ip)
        # Mensagem unica para senha errada: dizer "usuario nao existe" ou
        # "senha incorreta" entrega informacao de graca.
        return jsonify({"error": "Senha incorreta."}), 401

    auth.limpar_falhas(ip)
    session.permanent = True
    session["admin"] = True
    return jsonify({"ok": True})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/senha", methods=["POST"])
def api_auth_trocar_senha():
    """Troca a senha, exigindo a atual."""
    dados = request.get_json(silent=True) or {}
    atual = str(dados.get("atual") or "")
    nova = str(dados.get("nova") or "")

    if not auth.conferir_senha(atual, SETTINGS.get("ADMIN_PASSWORD_HASH")):
        return jsonify({"error": "A senha atual esta incorreta."}), 401

    problema = auth.forca_da_senha(nova)
    if problema:
        return jsonify({"error": problema}), 400

    SETTINGS["ADMIN_PASSWORD_HASH"] = auth.gerar_hash(nova)
    _save_config_file(SETTINGS)
    return jsonify({"ok": True})

# Armazenamento simples de jobs em memoria
JOBS = {}
JOBS_LOCK = threading.Lock()

# Biblioteca de videos pre-processados (normalizados e prontos para geracao).
LIBRARY = {}
LIBRARY_LOCK = threading.Lock()
LIBRARY_QUEUE = queue.Queue()
LIBRARY_WORKER_LOCK = threading.Lock()
LIBRARY_WORKER_STARTED = False


def _load_library_file():
    try:
        data = json.loads(LIBRARY_META_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_library_file():
    with LIBRARY_LOCK:
        payload = dict(LIBRARY)
    LIBRARY_META_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def init_library():
    global LIBRARY
    with LIBRARY_LOCK:
        LIBRARY = _load_library_file()


def get_library_item(item_id):
    with LIBRARY_LOCK:
        item = LIBRARY.get(item_id)
        return dict(item) if item else None


def set_library_item(item_id, **kwargs):
    with LIBRARY_LOCK:
        LIBRARY.setdefault(item_id, {})
        LIBRARY[item_id].update(kwargs)
        item = dict(LIBRARY[item_id])
    _save_library_file()
    return item


def normalize_tags(tags):
    out = []
    if not isinstance(tags, list):
        return out
    for t in tags:
        s = str(t or "").strip().lower()
        if not s or len(s) > 32:
            continue
        if s not in out:
            out.append(s)
    return out


def library_metrics():
    with LIBRARY_LOCK:
        items = list(LIBRARY.values())
    ready = processing = error = 0
    total_generations = total_outputs = 0
    tag_counts = {}
    for it in items:
        st = it.get("status", "")
        if st == "ready":
            ready += 1
        elif st == "processing":
            processing += 1
        elif st == "queued":
            processing += 1  # contabiliza em "processando" no painel
        elif st == "error":
            error += 1
        total_generations += int(it.get("generation_count") or 0)
        total_outputs += int(it.get("total_outputs") or 0)
        for tag in it.get("tags") or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return {
        "total": len(items),
        "ready": ready,
        "processing": processing,
        "error": error,
        "total_generations": total_generations,
        "total_outputs": total_outputs,
        "tag_counts": tag_counts,
    }


def library_record_generation(item_id, num_outputs):
    with LIBRARY_LOCK:
        item = LIBRARY.get(item_id)
        if not item:
            return
        item["generation_count"] = int(item.get("generation_count") or 0) + 1
        item["total_outputs"] = int(item.get("total_outputs") or 0) + int(num_outputs)
        tags = list(item.get("tags") or [])
        if "gerado" not in tags:
            tags.append("gerado")
        item["tags"] = tags
        item["last_generated_at"] = datetime.now(timezone.utc).isoformat()
    _save_library_file()


def preprocess_library_item(item_id, src_path):
    dst_path = LIBRARY_DIR / f"{item_id}.mp4"
    try:
        set_library_item(
            item_id,
            status="processing",
            message="Normalizando video (ffmpeg)...",
            error="",
        )
        normalize_video(src_path, dst_path)
        dur = media_duration(dst_path)
        size = dst_path.stat().st_size if dst_path.exists() else 0
        set_library_item(
            item_id,
            status="ready",
            file=f"{item_id}.mp4",
            message="Pronto para geracao.",
            error="",
            processed_at=datetime.now(timezone.utc).isoformat(),
            duration_sec=round(float(dur or 0), 2),
            size_bytes=size,
        )
    except Exception as e:  # noqa: BLE001
        set_library_item(
            item_id,
            status="error",
            message="Falha no pre-processamento.",
            error=str(e),
        )
        try:
            dst_path.unlink(missing_ok=True)
        except OSError:
            pass
    finally:
        try:
            Path(src_path).unlink(missing_ok=True)
        except OSError:
            pass


def _library_worker():
    """Processa um video por vez — evita N instancias ffmpeg em paralelo."""
    while True:
        item_id, src_path = LIBRARY_QUEUE.get()
        try:
            preprocess_library_item(item_id, src_path)
        finally:
            LIBRARY_QUEUE.task_done()


def _ensure_library_worker():
    global LIBRARY_WORKER_STARTED
    with LIBRARY_WORKER_LOCK:
        if LIBRARY_WORKER_STARTED:
            return
        thread = threading.Thread(
            target=_library_worker,
            name="library-preprocess-worker",
            daemon=True,
        )
        thread.start()
        LIBRARY_WORKER_STARTED = True


def _library_queue_message():
    pending = LIBRARY_QUEUE.qsize()
    if pending <= 1:
        return "Na fila de pre-processamento..."
    return f"Na fila de pre-processamento ({pending} aguardando)..."


def enqueue_library_preprocess(item_id, src_path):
    _ensure_library_worker()
    set_library_item(
        item_id,
        status="queued",
        message=_library_queue_message(),
        error="",
    )
    LIBRARY_QUEUE.put((item_id, str(src_path)))


def recover_library_on_startup():
    """Re-enfileira itens pendentes ou marca interrompidos apos reinicio."""
    with LIBRARY_LOCK:
        snapshot = list(LIBRARY.items())
    for item_id, item in snapshot:
        st = item.get("status")
        if st not in ("queued", "processing"):
            continue
        staging = next(LIBRARY_STAGING.glob(f"{item_id}.*"), None)
        if staging and staging.is_file():
            enqueue_library_preprocess(item_id, staging)
        else:
            set_library_item(
                item_id,
                status="error",
                message="Processamento interrompido.",
                error="Reenvie o video para pre-processar.",
            )


init_library()
store.init_store(STUDIO_DB_PATH)
secretbox.init_secretbox(USER_DATA_DIR)
recover_library_on_startup()


def find_system_font():
    """Fonte de texto de fallback caso a fonte arredondada nao exista."""
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def find_emoji_font():
    """Fonte com emojis coloridos (COLR/bitmap)."""
    candidates = [
        r"C:\Windows\Fonts\seguiemj.ttf",  # Segoe UI Emoji (Windows)
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/System/Library/Fonts/Apple Color Emoji.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


SYSTEM_FONT = find_system_font()
EMOJI_FONT = find_emoji_font()


def text_font_label():
    if ROUNDED_FONT_PATH.exists():
        return f"Quicksand ({ROUNDED_FONT_VARIATION})"
    return SYSTEM_FONT or "default"


# ---------------------------------------------------------------------------
# Normalizacao do upload via ffmpeg (antes de entregar ao MoviePy).
# Resolve videos problematicos: HDR/Dolby Vision 10-bit, rotacao por metadado
# (displaymatrix) e streams de dados (mebx) de iPhone, etc.
# ---------------------------------------------------------------------------

def _resolve_binary(name):
    """Localiza um binario (ffmpeg/ffprobe) priorizando os empacotados.

    Ordem: pasta `bin/` empacotada (sys._MEIPASS quando frozen) -> raiz do
    bundle -> PATH do sistema -> nome cru (ultimo recurso).
    """
    exe = name + (".exe" if os.name == "nt" else "")
    for cand in (resource_path(Path("bin") / exe), resource_path(exe)):
        if Path(cand).exists():
            return str(cand)
    found = shutil.which(name)
    return found or name


FFMPEG_BIN = _resolve_binary("ffmpeg")
FFPROBE_BIN = _resolve_binary("ffprobe")

# Garante que o MoviePy/imageio usem exatamente o mesmo ffmpeg (o empacotado).
if FFMPEG_BIN not in ("ffmpeg", "ffmpeg.exe") and Path(FFMPEG_BIN).exists():
    os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_BIN
    os.environ["FFMPEG_BINARY"] = FFMPEG_BIN

# Limite de altura final (acelera a renderizacao) agora vem de MAX_HEIGHT (settings).


def _ffprobe_video_info(path):
    """Retorna info de cor/pix_fmt do primeiro stream de video (ou {})."""
    try:
        proc = subprocess.run(
            [
                FFPROBE_BIN,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=color_transfer,color_primaries,color_space,pix_fmt",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        return streams[0] if streams else {}
    except Exception:  # noqa: BLE001
        return {}


def _is_hdr(info):
    transfer = (info.get("color_transfer") or "").lower()
    primaries = (info.get("color_primaries") or "").lower()
    # PQ (smpte2084) ou HLG (arib-std-b67), ou gamut bt2020.
    return transfer in ("smpte2084", "arib-std-b67") or primaries in (
        "bt2020",
        "bt2020nc",
        "bt2020c",
    )


def _run_ffmpeg(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, (proc.stderr or "")[-800:]


def normalize_video(src_path, dst_path):
    """Transcodifica o upload para um MP4 H.264/AAC 8-bit SDR "limpo":
    - mapeia apenas video+audio (descarta streams de dados/mebx);
    - aplica rotacao fisicamente (autorotate) e zera o metadado rotate;
    - converte HDR/10-bit (Dolby Vision/PQ/HLG) para SDR 8-bit com tonemap;
    - limita a altura a MAX_HEIGHT mantendo a proporcao;
    - libx264 + aac + faststart.
    """
    info = _ffprobe_video_info(src_path)
    hdr = _is_hdr(info)

    # min(MAX_HEIGHT, ih) com a virgula escapada dentro do filtergraph.
    scale = f"scale=-2:'min({MAX_HEIGHT}\\,ih)'"

    if hdr:
        vf = (
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
            f"{scale},format=yuv420p"
        )
    else:
        vf = f"{scale},format=yuv420p"

    base_out = [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "160k",
        "-metadata:s:v:0", "rotate=0",
        "-movflags", "+faststart",
        str(dst_path),
    ]

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(src_path),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-vf", vf,
        *base_out,
    ]

    code, err = _run_ffmpeg(cmd)
    if code == 0 and Path(dst_path).exists() and Path(dst_path).stat().st_size > 0:
        return

    # Fallback: sem tonemap zscale (caso o filtro falhe), so converte para 8-bit.
    fallback_vf = f"{scale},format=yuv420p"
    fallback_cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(src_path),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-vf", fallback_vf,
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        *base_out,
    ]
    code2, err2 = _run_ffmpeg(fallback_cmd)
    if code2 == 0 and Path(dst_path).exists() and Path(dst_path).stat().st_size > 0:
        return

    raise RuntimeError(
        "Falha ao normalizar o video com ffmpeg. "
        f"Detalhe: {err2 or err}"
    )


# ---------------------------------------------------------------------------
# Renderizacao de texto com Pillow: combina fonte arredondada (texto) com
# fonte de emoji colorido, com contorno, quebra de linha e centralizacao.
# ---------------------------------------------------------------------------

_JOINERS = {0x200D, 0xFE0F, 0xFE0E, 0x20E3}


def _is_emoji(cp):
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2300 <= cp <= 0x23FF
        or 0x2B00 <= cp <= 0x2BFF
        or 0x1F1E6 <= cp <= 0x1F1FF
        or cp in (0x2122, 0x2139, 0x24C2, 0x3030, 0x303D, 0x3297, 0x3299)
    )


def segment_runs(text):
    """Divide o texto em trechos consecutivos (is_emoji, substring)."""
    runs = []
    buf = []
    buf_emoji = None
    for ch in text:
        cp = ord(ch)
        if cp in _JOINERS or 0x1F3FB <= cp <= 0x1F3FF:
            # Modificadores/joiners grudam no trecho atual (emoji).
            if buf:
                buf.append(ch)
            else:
                buf = [ch]
                buf_emoji = True
            continue
        e = _is_emoji(cp)
        if buf and e == buf_emoji:
            buf.append(ch)
        else:
            if buf:
                runs.append((buf_emoji, "".join(buf)))
            buf = [ch]
            buf_emoji = e
    if buf:
        runs.append((buf_emoji, "".join(buf)))
    return runs


def load_text_font(size):
    if ROUNDED_FONT_PATH.exists():
        f = ImageFont.truetype(str(ROUNDED_FONT_PATH), size)
        try:
            f.set_variation_by_name(ROUNDED_FONT_VARIATION)
        except Exception:  # noqa: BLE001
            pass
        return f
    if SYSTEM_FONT:
        return ImageFont.truetype(SYSTEM_FONT, size)
    return ImageFont.load_default()


def load_emoji_font(size):
    if not EMOJI_FONT:
        return None
    try:
        return ImageFont.truetype(EMOJI_FONT, size)
    except Exception:  # noqa: BLE001
        # Algumas fontes de emoji sao bitmap e so aceitam tamanhos fixos.
        for s in (size, 109, 137, 96):
            try:
                return ImageFont.truetype(EMOJI_FONT, s)
            except Exception:  # noqa: BLE001
                continue
    return None


def render_text_image(
    text, font_size, color, stroke_color, stroke_width, max_width, line_spacing=0.95
):
    """Gera uma imagem RGBA transparente com o texto (fonte arredondada) e os
    emojis coloridos, com contorno, quebra de linha (caption) e centralizado.

    line_spacing e o multiplicador de espacamento entre linhas (1.0 = altura da
    linha; valores maiores afastam as linhas)."""
    text_font = load_text_font(font_size)
    emoji_font = load_emoji_font(font_size)

    ascent, descent = text_font.getmetrics()
    line_height = ascent + descent
    # Distancia (em pixels) entre as baselines de duas linhas consecutivas.
    step = max(line_height * 0.5, line_height * float(line_spacing))
    space_w = text_font.getlength(" ")

    def run_width(is_e, run):
        if is_e:
            if not emoji_font:
                return 0.0
            try:
                return emoji_font.getlength(run)
            except Exception:  # noqa: BLE001
                return text_font.getlength(run)
        return text_font.getlength(run)

    def measure(s):
        return sum(run_width(is_e, run) for is_e, run in segment_runs(s))

    # Quebra de linha respeitando \n explicitos e largura maxima (por palavra).
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        cur = ""
        cur_w = 0.0
        for word in words:
            ww = measure(word)
            add = ww if not cur else space_w + ww
            if cur and cur_w + add > max_width:
                lines.append(cur)
                cur = word
                cur_w = ww
            else:
                cur = word if not cur else cur + " " + word
                cur_w += add
        lines.append(cur)
    if not lines:
        lines = [""]

    pad = stroke_width + 6
    max_line_w = max((measure(ln) for ln in lines), default=1.0)
    block_w = max(1, int(max_line_w) + 2 * pad)
    block_h = int(round(line_height + (len(lines) - 1) * step + 2 * pad))

    img = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        line_w = measure(line)
        x = (block_w - line_w) / 2
        baseline_y = pad + i * step + ascent
        for is_e, run in segment_runs(line):
            if is_e:
                if not emoji_font:
                    continue  # sem glifo -> nao desenha tofu
                try:
                    draw.text(
                        (x, baseline_y),
                        run,
                        font=emoji_font,
                        anchor="ls",
                        embedded_color=True,
                    )
                    x += run_width(True, run)
                except Exception:  # noqa: BLE001
                    x += run_width(True, run)
            else:
                draw.text(
                    (x, baseline_y),
                    run,
                    font=text_font,
                    fill=color,
                    anchor="ls",
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color,
                )
                x += run_width(False, run)

    return img


def set_job(job_id, **kwargs):
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {})
        JOBS[job_id].update(kwargs)


def get_job(job_id):
    with JOBS_LOCK:
        return dict(JOBS.get(job_id, {}))


def generate_phrases(n, theme, extra_tags=None):
    """Chama a OpenRouter SOMENTE com texto e retorna n itens prontos para o post.

    Cada item traz a frase da tela, a legenda do post e as hashtags - tudo na
    mesma chamada, para a legenda ficar coerente com a frase sem custar um
    segundo request. O video NUNCA e enviado para a API.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY nao configurada. Crie um arquivo .env (veja .env.example)."
        )

    theme_part = (
        f'O tema/contexto do video e: "{theme}".'
        if theme
        else "O video e generico, crie frases chamativas de uso geral para redes sociais."
    )

    system_prompt = (
        "Voce e um redator de copy para videos curtos virais (TikTok/Reels/Shorts). "
        "Escreve em portugues do Brasil, com frases curtas e impactantes, prontas "
        "para serem sobrepostas no video, e legendas de post que dao vontade de "
        "assistir ate o fim."
    )

    user_prompt = (
        f"{theme_part}\n\n"
        f"Gere exatamente {n} itens DIFERENTES entre si. Cada item tem:\n"
        '- "overlay": a frase que fica NA TELA do video, no maximo 120 caracteres '
        "(pode usar 1 ou 2 emojis);\n"
        '- "caption": a legenda do post, curta, no maximo 150 caracteres, '
        "SEM hashtags dentro dela;\n"
        f'- "hashtags": no maximo {cap.MAX_HASHTAGS} hashtags relevantes, sem o '
        "simbolo #, sem espacos e sem acentos.\n\n"
        "Responda APENAS com um JSON valido no formato: "
        '{"itens": [{"overlay": "...", "caption": "...", "hashtags": ["..."]}]}. '
        "Nao inclua explicacoes, numeracao ou texto fora do JSON."
    )

    content = _openrouter_chat(system_prompt, user_prompt)
    items = parse_phrases(content, n)
    if not items:
        raise RuntimeError("A IA nao retornou frases validas.")

    for item in items:
        item["caption"], item["hashtags"] = cap.finalize(
            item.get("caption"),
            item.get("hashtags"),
            phrase=item.get("overlay", ""),
            theme=theme,
            extra_tags=extra_tags,
        )
    return items[:n]


def parse_phrases(content, n):
    """Extrai [{overlay, caption, hashtags}] da resposta da IA, de forma tolerante.

    Aceita tanto o formato novo quanto o antigo ({"frases": [...]}) e, em ultimo
    caso, linhas soltas - a legenda entra vazia e o fallback preenche depois.
    """
    content = (content or "").strip()
    items = []

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            raw = data.get("itens") or data.get("items")
            if isinstance(raw, list):
                for it in raw:
                    if not isinstance(it, dict):
                        continue
                    overlay = str(
                        it.get("overlay") or it.get("frase") or it.get("phrase") or ""
                    ).strip()
                    if not overlay:
                        continue
                    items.append(
                        {
                            "overlay": overlay,
                            "caption": str(it.get("caption") or it.get("legenda") or ""),
                            "hashtags": it.get("hashtags") or it.get("tags") or [],
                        }
                    )
            if not items:
                # Formato antigo: {"frases": ["...", "..."]}
                frases = data.get("frases") or data.get("phrases")
                if isinstance(frases, list):
                    items = [
                        {"overlay": str(f).strip(), "caption": "", "hashtags": []}
                        for f in frases
                        if str(f).strip()
                    ]

    if not items:
        lines = [
            re.sub(r"^\s*[\d\-\.\)\"]+\s*", "", ln).strip().strip('"')
            for ln in content.splitlines()
            if ln.strip()
        ]
        items = [
            {"overlay": ln, "caption": "", "hashtags": []} for ln in lines if ln
        ]

    return items[:n]


def media_duration(path):
    """Duracao (segundos) de um arquivo de midia via ffprobe (0.0 se falhar)."""
    try:
        proc = subprocess.run(
            [
                FFPROBE_BIN,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return float((proc.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _openrouter_chat(system_prompt, user_prompt, temperature=0.9):
    """Chamada generica de chat na OpenRouter (apenas texto)."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY nao configurada. Crie um arquivo .env (veja .env.example)."
        )
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "IA Video Generator",
    }
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Erro da OpenRouter ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


def words_target_for_duration(duration):
    """Numero maximo de palavras da narracao para caber na duracao do video,
    com margem de seguranca para nao estourar."""
    if duration <= 0:
        duration = 8.0
    return max(6, int(duration * WORDS_PER_SECOND * 0.85))


def generate_overlay_and_speech(n, theme, video_duration, extra_tags=None):
    """Gera n itens coerentes (overlay na tela + narracao + legenda do post),
    usando tecnicas de videos virais de TikTok e respeitando o limite de
    palavras compativel com a duracao do video. So texto vai para a IA."""
    # Alvo de palavras baseado na duracao do video + 10s (a montagem estende o
    # ultimo frame para caber a narracao mais longa).
    budget_duration = (video_duration if video_duration > 0 else 8.0) + 10
    words_max = words_target_for_duration(budget_duration)
    theme_part = (
        f'Tema/contexto do video: "{theme}".'
        if theme
        else "O video e generico; crie ganchos chamativos de uso geral."
    )

    system_prompt = (
        "Voce e um roteirista especialista em videos virais de TikTok/Reels/Shorts "
        "em portugues do Brasil. Aplique tecnicas de viralizacao: HOOK forte nos "
        "primeiros segundos, linguagem coloquial e direta, gatilhos de curiosidade e "
        "retencao, frases curtas e ritmadas, e uma call-to-action no final."
    )

    user_prompt = (
        f"{theme_part}\n\n"
        f"O video tem cerca de {video_duration:.0f} segundos.\n"
        f"Gere exatamente {n} itens DIFERENTES entre si. Cada item tem:\n"
        "- \"overlay\": frase curta e impactante para FICAR NA TELA do video "
        "(maximo ~8 palavras, pode usar 1 emoji);\n"
        "- \"speech\": o texto da NARRACAO falada, coerente com a overlay, "
        f"com no MAXIMO {words_max} palavras para caber em ~{budget_duration:.0f}s "
        "(ritmo de fala natural). NAO use emojis na speech;\n"
        "- \"caption\": a legenda do post, curta, no maximo 150 caracteres, "
        "SEM hashtags dentro dela;\n"
        f"- \"hashtags\": no maximo {cap.MAX_HASHTAGS} hashtags relevantes, sem o "
        "simbolo #, sem espacos e sem acentos.\n\n"
        "Responda APENAS com JSON valido no formato: "
        '{"itens": [{"overlay": "...", "speech": "...", "caption": "...", '
        '"hashtags": ["..."]}]}. '
        "Sem explicacoes nem texto fora do JSON."
    )

    content = _openrouter_chat(system_prompt, user_prompt)
    items = parse_overlay_speech(content, n)
    if not items:
        raise RuntimeError("A IA nao retornou overlay/speech validos.")

    for item in items:
        item["caption"], item["hashtags"] = cap.finalize(
            item.get("caption"),
            item.get("hashtags"),
            phrase=item.get("overlay", ""),
            theme=theme,
            extra_tags=extra_tags,
        )
    return items[:n]


def parse_overlay_speech(content, n):
    """Extrai [{overlay, speech, caption, hashtags}] da resposta da IA."""
    content = (content or "").strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    data = None
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
    items = []
    if isinstance(data, dict):
        raw = data.get("itens") or data.get("items") or data.get("results")
        if isinstance(raw, list):
            for it in raw:
                if not isinstance(it, dict):
                    continue
                overlay = str(it.get("overlay") or it.get("frase") or "").strip()
                speech = str(it.get("speech") or it.get("fala") or "").strip()
                if overlay or speech:
                    items.append(
                        {
                            "overlay": overlay or speech,
                            "speech": speech or overlay,
                            "caption": str(it.get("caption") or it.get("legenda") or ""),
                            "hashtags": it.get("hashtags") or it.get("tags") or [],
                        }
                    )
    return items[:n]


def elevenlabs_tts(text, voice_id, model_id, stability, similarity, out_path):
    """Gera a narracao (mp3) na ElevenLabs. Apenas texto e enviado."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ELEVENLABS_API_KEY nao configurada. Adicione-a ao .env para usar o modo com audio."
        )
    if not voice_id:
        raise RuntimeError("Voice ID da ElevenLabs nao informado.")

    url = f"{ELEVENLABS_URL}/{voice_id}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id or ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
        },
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Erro da ElevenLabs ({resp.status_code}): {resp.text[:300]}"
        )
    with open(out_path, "wb") as f:
        f.write(resp.content)
    if Path(out_path).stat().st_size == 0:
        raise RuntimeError("A ElevenLabs retornou um audio vazio.")


def compute_position(video_w, video_h, txt_w, txt_h, vertical, jitter=True):
    """Calcula a posicao (x, y) em pixels. O texto fica centralizado na
    horizontal; a altura e definida por `vertical` (0.0 = topo .. 1.0 = base),
    com um pequeno jitter aleatorio e clamp para manter dentro do quadro."""
    margin_x = max(8, int(video_w * 0.03))
    margin_y = max(8, int(video_h * 0.03))

    try:
        vertical = float(vertical)
    except (TypeError, ValueError):
        vertical = 0.5
    vertical = max(0.0, min(1.0, vertical))

    base_x = (video_w - txt_w) / 2
    usable_v = (video_h - txt_h) - 2 * margin_y
    if usable_v > 0:
        base_y = margin_y + vertical * usable_v
    else:
        base_y = (video_h - txt_h) / 2

    if jitter:
        jx = random.uniform(-1, 1) * min(video_w * 0.05, 45)
        jy = random.uniform(-1, 1) * min(video_h * 0.04, 40)
    else:
        jx = jy = 0

    x = base_x + jx
    y = base_y + jy

    # Mantem dentro do quadro (com margem). Se o texto for maior que o espaco
    # util, centraliza no eixo correspondente.
    if video_w - txt_w - 2 * margin_x > 0:
        x = max(margin_x, min(x, video_w - txt_w - margin_x))
    else:
        x = max(0, (video_w - txt_w) / 2)

    if video_h - txt_h - 2 * margin_y > 0:
        y = max(margin_y, min(y, video_h - txt_h - margin_y))
    else:
        y = max(0, (video_h - txt_h) / 2)

    return (int(round(x)), int(round(y)))


def render_video(src_path, text, out_path, options, audio_path=None):
    """Sobrepoe o texto (fonte arredondada + emojis coloridos) no video,
    100% local, usando uma imagem RGBA gerada com Pillow.

    Se audio_path for informado, usa esse audio (narracao ElevenLabs) como
    trilha principal. Se a narracao for mais longa que o video, o ultimo frame
    e congelado para o audio caber; se for mais curta, o audio fica no inicio
    (silencio no fim)."""
    video = VideoFileClip(str(src_path))
    narration = None
    txt_clip = None
    base = video
    try:
        target_dur = video.duration

        if audio_path:
            narration = AudioFileClip(str(audio_path))
            if narration.duration > video.duration + 0.05:
                # Congela o ultimo frame para estender o video ate o fim do audio.
                extra = narration.duration - video.duration
                freeze = video.to_ImageClip(
                    t=max(0.0, video.duration - 0.05)
                ).with_duration(extra)
                base = concatenate_videoclips([video, freeze])
                target_dur = narration.duration
            else:
                target_dur = video.duration

        clip_width = max(300, int(video.w * 0.85))
        img = render_text_image(
            text,
            options["font_size"],
            options["color"],
            options["stroke_color"],
            options["stroke_width"],
            clip_width,
            options["line_spacing"],
        )

        arr = np.array(img)
        rgb = arr[:, :, :3]
        alpha = arr[:, :, 3].astype("float64") / 255.0

        txt_clip = ImageClip(rgb).with_duration(target_dur)
        mask = ImageClip(alpha, is_mask=True).with_duration(target_dur)
        txt_clip = txt_clip.with_mask(mask)

        txt_w, txt_h = img.size
        pos = compute_position(
            video.w, video.h, txt_w, txt_h, options.get("vertical", 0.5), jitter=True
        )
        txt_clip = txt_clip.with_position(pos)

        final = CompositeVideoClip([base, txt_clip]).with_duration(target_dur)

        if narration is not None:
            # Narracao como trilha principal (silencia o audio original do video).
            final = final.with_audio(narration)

        final.write_videofile(
            str(out_path),
            fps=options["fps"],
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )
        final.close()
    finally:
        if txt_clip is not None:
            txt_clip.close()
        if narration is not None:
            try:
                narration.close()
            except Exception:  # noqa: BLE001
                pass
        video.close()


def process_job(job_id, src_path, num, theme, options, audio_opts=None,
                library_id=None, source_name=""):
    owns_src = bool(src_path)
    owns_norm = library_id is None
    norm_path = None
    audio_files = []

    if library_id:
        item = get_library_item(library_id)
        if not item or item.get("status") != "ready":
            set_job(job_id, status="error", message="Video da biblioteca indisponivel.")
            return
        norm_path = LIBRARY_DIR / str(item.get("file") or f"{library_id}.mp4")
        if not norm_path.exists():
            set_job(job_id, status="error", message="Arquivo da biblioteca nao encontrado.")
            return
    else:
        norm_path = UPLOAD_DIR / f"{job_id}_norm.mp4"

    try:
        if library_id:
            set_job(
                job_id,
                status="generating_text",
                message="Usando video pre-processado da biblioteca...",
                progress=5,
            )
        else:
            set_job(
                job_id,
                status="normalizing",
                message="Normalizando o video (ffmpeg)...",
                progress=0,
            )
            normalize_video(src_path, norm_path)

        audio_mode = bool(audio_opts and audio_opts.get("enabled"))
        # As tags do video-fonte alimentam o fallback de hashtags quando a IA
        # nao devolve nenhuma.
        lib_item = get_library_item(library_id) if library_id else None
        extra_tags = list((lib_item or {}).get("tags") or [])

        if audio_mode:
            video_dur = media_duration(norm_path)
            set_job(
                job_id,
                status="generating_text",
                message="Gerando roteiro, narracao e legenda com a IA...",
            )
            audio_theme = audio_opts.get("theme") or theme
            items = generate_overlay_and_speech(
                num, audio_theme, video_dur, extra_tags=extra_tags
            )

            results = []
            total = len(items)
            for i, item in enumerate(items, start=1):
                set_job(
                    job_id,
                    status="tts",
                    message=f"Gerando audio (ElevenLabs) {i} de {total}...",
                    progress=int((i - 1) / total * 100),
                )
                audio_path = UPLOAD_DIR / f"{job_id}_{i}.mp3"
                audio_files.append(audio_path)
                elevenlabs_tts(
                    item["speech"],
                    audio_opts.get("voice_id", ""),
                    audio_opts.get("model_id", ELEVENLABS_MODEL),
                    audio_opts.get("stability", 0.5),
                    audio_opts.get("similarity", 0.75),
                    audio_path,
                )

                set_job(
                    job_id,
                    status="rendering",
                    message=f"Montando video {i} de {total}...",
                    progress=int((i - 0.5) / total * 100),
                )
                out_name = f"{job_id}_{i}.mp4"
                out_path = OUTPUT_DIR / out_name
                render_video(
                    norm_path, item["overlay"], out_path, options, audio_path=audio_path
                )
                record = store.add_output(
                    file=out_name,
                    job_id=job_id,
                    library_id=library_id or "",
                    phrase=item["overlay"],
                    speech=item["speech"],
                    caption=item.get("caption", ""),
                    hashtags=item.get("hashtags", []),
                    theme=audio_theme,
                    source_name=source_name,
                    duration=media_duration(out_path),
                    audio_mode=True,
                )
                results.append(
                    {
                        "id": record["id"],
                        "phrase": item["overlay"],
                        "speech": item["speech"],
                        "caption": record["caption"],
                        "hashtags": record["hashtags"],
                        "file": out_name,
                    }
                )
                set_job(job_id, results=results, progress=int(i / total * 100))
        else:
            set_job(
                job_id,
                status="generating_text",
                message="Gerando frases e legendas com a IA...",
            )
            phrases = generate_phrases(num, theme, extra_tags=extra_tags)

            results = []
            total = len(phrases)
            for i, item in enumerate(phrases, start=1):
                phrase = item["overlay"]
                set_job(
                    job_id,
                    status="rendering",
                    message=f"Renderizando video {i} de {total}...",
                    progress=int((i - 1) / total * 100),
                )
                out_name = f"{job_id}_{i}.mp4"
                out_path = OUTPUT_DIR / out_name
                render_video(norm_path, phrase, out_path, options)
                record = store.add_output(
                    file=out_name,
                    job_id=job_id,
                    library_id=library_id or "",
                    phrase=phrase,
                    caption=item.get("caption", ""),
                    hashtags=item.get("hashtags", []),
                    theme=theme,
                    source_name=source_name,
                    duration=media_duration(out_path),
                )
                results.append(
                    {
                        "id": record["id"],
                        "phrase": phrase,
                        "caption": record["caption"],
                        "hashtags": record["hashtags"],
                        "file": out_name,
                    }
                )
                set_job(job_id, results=results, progress=int(i / total * 100))

        set_job(
            job_id,
            status="done",
            message="Concluido!",
            progress=100,
            results=results,
        )
        if library_id:
            library_record_generation(library_id, len(results))
    except Exception as e:  # noqa: BLE001
        set_job(job_id, status="error", message=str(e))
    finally:
        cleanup = []
        if owns_src and src_path:
            cleanup.append(src_path)
        if owns_norm and norm_path:
            cleanup.append(norm_path)
        cleanup.extend(audio_files)
        for p in cleanup:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass


@app.route("/api/<path:_unused>", methods=["OPTIONS"])
def api_preflight(_unused):
    return ("", 204)


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "app": "Studio Native"})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    library_id = request.form.get("library_id", "").strip()
    src_path = None

    if library_id:
        item = get_library_item(library_id)
        if not item:
            return jsonify({"error": "Video da biblioteca nao encontrado."}), 404
        if item.get("status") != "ready":
            return jsonify(
                {"error": "Video ainda em processamento ou com erro. Aguarde ou reenvie."}
            ), 400
    else:
        if "video" not in request.files:
            return jsonify({"error": "Nenhum video enviado."}), 400

        file = request.files["video"]
        if not file.filename:
            return jsonify({"error": "Arquivo invalido."}), 400

        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({"error": f"Formato nao suportado: {ext}"}), 400

    try:
        num = int(request.form.get("num_variations", "1"))
    except ValueError:
        num = 1
    num = max(1, min(num, 10))

    theme = request.form.get("theme", "").strip()

    try:
        line_spacing = float(request.form.get("line_spacing", 0.95))
    except ValueError:
        line_spacing = 0.95
    line_spacing = max(0.8, min(line_spacing, 2.0))

    # Altura vertical da frase: valor continuo 0.0 (topo) .. 1.0 (base).
    # Aceita tambem percentagem (0..100) e o campo antigo `position`.
    try:
        vertical = float(request.form.get("vertical", 0.5))
    except (TypeError, ValueError):
        vertical = 0.5
    if vertical > 1.0:
        vertical = vertical / 100.0
    pos_legacy = request.form.get("position")
    if "vertical" not in request.form and pos_legacy:
        vertical = {"top": 0.06, "center": 0.5, "bottom": 0.94}.get(pos_legacy, 0.5)
    vertical = max(0.0, min(1.0, vertical))

    options = {
        "font_size": int(request.form.get("font_size", 40)),
        "color": request.form.get("color", "#ffffff"),
        "stroke_color": request.form.get("stroke_color", "#000000"),
        "stroke_width": int(request.form.get("stroke_width", 5)),
        "vertical": vertical,
        "fps": int(request.form.get("fps", 30)),
        "line_spacing": line_spacing,
    }

    # Modo com audio (narracao ElevenLabs)
    audio_enabled = request.form.get("audio_enabled", "").lower() in (
        "1", "true", "on", "yes",
    )
    audio_opts = {"enabled": audio_enabled}
    if audio_enabled:
        if not ELEVENLABS_API_KEY:
            return jsonify(
                {"error": "ELEVENLABS_API_KEY nao configurada. Abra Ajustes para informar a chave."}
            ), 400

        voice_profile_id = request.form.get("voice_profile_id", "").strip()
        voice_profile = None
        if voice_profile_id:
            voice_profile = next((v for v in VOICES if v.get("id") == voice_profile_id), None)
            if not voice_profile:
                return jsonify({"error": "Voz cadastrada nao encontrada nos Ajustes."}), 400

        voice_id = (
            str(voice_profile.get("voice_id", "")).strip()
            if voice_profile
            else request.form.get("voice_id", "").strip()
        )
        if not voice_id:
            return jsonify({"error": "Selecione uma voz cadastrada nos Ajustes."}), 400

        def _clamp01(v, default):
            try:
                return max(0.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                return default

        model_id = request.form.get("audio_model_id", "").strip() or ELEVENLABS_MODEL
        stability = _clamp01(request.form.get("stability"), 0.5)
        similarity = _clamp01(request.form.get("similarity"), 0.75)
        if voice_profile:
            model_id = str(voice_profile.get("model_id") or ELEVENLABS_MODEL).strip()
            stability = _clamp01(voice_profile.get("stability"), 0.5)
            similarity = _clamp01(voice_profile.get("similarity"), 0.75)

        audio_opts.update(
            {
                "voice_id": voice_id,
                "model_id": model_id,
                "stability": stability,
                "similarity": similarity,
                "theme": request.form.get("audio_theme", "").strip(),
            }
        )

    job_id = uuid.uuid4().hex
    if library_id:
        source_name = str((get_library_item(library_id) or {}).get("name") or "")
    else:
        source_name = file.filename or ""
        src_path = UPLOAD_DIR / f"{job_id}{ext}"
        file.save(str(src_path))

    set_job(job_id, status="queued", message="Na fila...", progress=0, results=[])

    thread = threading.Thread(
        target=process_job,
        args=(job_id, src_path, num, theme, options, audio_opts),
        kwargs={"library_id": library_id or None, "source_name": source_name},
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job nao encontrado."}), 404
    return jsonify(job)


@app.route("/outputs/<path:filename>")
def outputs(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/library/<path:filename>")
def library_file(filename):
    return send_from_directory(LIBRARY_DIR, filename)


# ---------------------------------------------------------------------------
# Catalogo de producao: os videos que o app gerou, com legenda e hashtags.
# ---------------------------------------------------------------------------

@app.route("/api/outputs", methods=["GET"])
def api_outputs_list():
    items = store.list_outputs(
        status=request.args.get("status") or None,
        library_id=request.args.get("library_id") or None,
        job_id=request.args.get("job_id") or None,
        search=request.args.get("q") or None,
        limit=int(request.args.get("limit", 200)),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"items": items, "metrics": store.metrics()})


@app.route("/api/outputs/<output_id>", methods=["GET"])
def api_output_get(output_id):
    item = store.get_output(output_id)
    if not item:
        return jsonify({"error": "Video nao encontrado."}), 404
    return jsonify(item)


@app.route("/api/outputs/<output_id>", methods=["PATCH"])
def api_output_patch(output_id):
    if not store.get_output(output_id):
        return jsonify({"error": "Video nao encontrado."}), 404
    data = request.get_json(silent=True) or {}
    fields = {}
    if "caption" in data:
        fields["caption"] = cap.clean_caption(data.get("caption"))
    if "hashtags" in data:
        # O limite de 5 e do backend: a UI pode sugerir, mas nao decide.
        fields["hashtags"] = cap.normalize_hashtags(data.get("hashtags"))
    if "status" in data:
        fields["status"] = str(data.get("status") or "pronto")
    return jsonify(store.update_output(output_id, **fields))


@app.route("/api/outputs/<output_id>", methods=["DELETE"])
def api_output_delete(output_id):
    item = store.delete_output(output_id)
    if not item:
        return jsonify({"error": "Video nao encontrado."}), 404
    try:
        (OUTPUT_DIR / item["file"]).unlink(missing_ok=True)
    except OSError:
        pass
    return jsonify({"ok": True})


@app.route("/api/outputs/<output_id>/caption", methods=["POST"])
def api_output_caption_regenerate(output_id):
    """Gera outra legenda para um video ja renderizado, sem re-renderizar."""
    item = store.get_output(output_id)
    if not item:
        return jsonify({"error": "Video nao encontrado."}), 404

    lib_item = get_library_item(item.get("library_id")) if item.get("library_id") else None
    extra_tags = list((lib_item or {}).get("tags") or [])
    try:
        variants = generate_phrases(1, item.get("theme") or item.get("phrase"), extra_tags)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 502

    fresh = variants[0]
    updated = store.update_output(
        output_id, caption=fresh["caption"], hashtags=fresh["hashtags"]
    )
    return jsonify(updated)


@app.route("/api/outputs/import", methods=["POST"])
def api_outputs_import():
    """Migra o historico que vivia no localStorage do React para o catalogo.

    Idempotente: roda quantas vezes quiser, so importa o que ainda nao existe e
    cujo arquivo continua em outputs/.
    """
    data = request.get_json(silent=True) or {}
    existing = {p.name for p in OUTPUT_DIR.glob("*.mp4")}
    result = store.import_history(data.get("entries") or [], existing)
    return jsonify(result)


@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    return jsonify(store.metrics())


@app.route("/api/library", methods=["GET"])
def api_library_list():
    with LIBRARY_LOCK:
        items = sorted(
            (dict(v) for v in LIBRARY.values()),
            key=lambda x: x.get("created_at") or "",
            reverse=True,
        )
    counts = store.counts_by_library()
    for item in items:
        c = counts.get(item.get("id")) or {}
        item["produced_count"] = c.get("produced", 0)
        item["published_count"] = c.get("published", 0)
    metrics = library_metrics()
    metrics.update(store.metrics())
    return jsonify({"items": items, "metrics": metrics})


@app.route("/api/library/upload", methods=["POST"])
def api_library_upload():
    if "video" not in request.files:
        return jsonify({"error": "Nenhum video enviado."}), 400
    file = request.files["video"]
    if not file.filename:
        return jsonify({"error": "Arquivo invalido."}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Formato nao suportado: {ext}"}), 400

    item_id = uuid.uuid4().hex
    staging = LIBRARY_STAGING / f"{item_id}{ext}"
    file.save(str(staging))

    now = datetime.now(timezone.utc).isoformat()
    set_library_item(
        item_id,
        id=item_id,
        name=file.filename,
        status="queued",
        message="Na fila de pre-processamento...",
        error="",
        tags=[],
        generation_count=0,
        total_outputs=0,
        created_at=now,
        processed_at="",
        duration_sec=0,
        size_bytes=0,
        file="",
    )

    enqueue_library_preprocess(item_id, staging)
    return jsonify({"id": item_id, "item": get_library_item(item_id)})


@app.route("/api/library/<item_id>", methods=["GET"])
def api_library_get(item_id):
    item = get_library_item(item_id)
    if not item:
        return jsonify({"error": "Video nao encontrado."}), 404
    return jsonify(item)


@app.route("/api/library/<item_id>", methods=["PATCH"])
def api_library_patch(item_id):
    item = get_library_item(item_id)
    if not item:
        return jsonify({"error": "Video nao encontrado."}), 404
    data = request.get_json(silent=True) or {}
    if "tags" in data:
        set_library_item(item_id, tags=normalize_tags(data.get("tags")))
    return jsonify(get_library_item(item_id))


@app.route("/api/library/<item_id>", methods=["DELETE"])
def api_library_delete(item_id):
    item = get_library_item(item_id)
    if not item:
        return jsonify({"error": "Video nao encontrado."}), 404
    fname = item.get("file")
    with LIBRARY_LOCK:
        LIBRARY.pop(item_id, None)
    _save_library_file()
    if fname:
        try:
            (LIBRARY_DIR / fname).unlink(missing_ok=True)
        except OSError:
            pass
    return jsonify({"ok": True})


@app.route("/api/config")
def api_config():
    return jsonify(
        {
            "model": OPENROUTER_MODEL,
            "api_key_set": bool(OPENROUTER_API_KEY),
            "text_font": text_font_label(),
            "emoji_font": EMOJI_FONT,
            "elevenlabs_available": bool(ELEVENLABS_API_KEY),
            "elevenlabs_model": ELEVENLABS_MODEL,
            "max_height": MAX_HEIGHT,
            "voices": VOICES,
        }
    )


def _mask_key(value):
    """Mascara uma chave para exibicao (ex.: 'sk-or...AB12')."""
    v = str(value or "")
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}...{v[-4:]}"


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(
        {
            "openrouter_model": OPENROUTER_MODEL,
            "elevenlabs_model": ELEVENLABS_MODEL,
            "max_height": MAX_HEIGHT,
            "openrouter_key_set": bool(OPENROUTER_API_KEY),
            "elevenlabs_key_set": bool(ELEVENLABS_API_KEY),
            "openrouter_key_masked": _mask_key(OPENROUTER_API_KEY),
            "elevenlabs_key_masked": _mask_key(ELEVENLABS_API_KEY),
            "config_path": str(CONFIG_PATH),
            "voices": VOICES,
        }
    )


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    global SETTINGS
    data = request.get_json(silent=True) or {}

    # Persistimos sempre o conjunto completo no config.json (defaults + atual).
    stored = dict(SETTINGS)

    # Modelos / numericos: aceitam atualizacao direta (string vazia volta ao default).
    if "openrouter_model" in data:
        stored["OPENROUTER_MODEL"] = (
            str(data.get("openrouter_model") or "").strip()
            or SETTINGS_DEFAULTS["OPENROUTER_MODEL"]
        )
    if "elevenlabs_model" in data:
        stored["ELEVENLABS_MODEL"] = (
            str(data.get("elevenlabs_model") or "").strip()
            or SETTINGS_DEFAULTS["ELEVENLABS_MODEL"]
        )
    if "max_height" in data:
        try:
            stored["MAX_HEIGHT"] = max(240, min(2160, int(data.get("max_height"))))
        except (TypeError, ValueError):
            pass

    # Chaves secretas: so atualizam quando o campo vier no payload.
    # String vazia => limpar; ausente => manter o valor atual.
    if "openrouter_api_key" in data:
        stored["OPENROUTER_API_KEY"] = str(data.get("openrouter_api_key") or "").strip()
    if "elevenlabs_api_key" in data:
        stored["ELEVENLABS_API_KEY"] = str(data.get("elevenlabs_api_key") or "").strip()

    # Biblioteca de vozes (ElevenLabs).
    if "voices" in data:
        stored["voices"] = normalize_voices(data.get("voices"))

    SETTINGS = stored
    apply_settings()
    _save_config_file(stored)

    return api_settings_get()


# ---------------------------------------------------------------------------
# Modo navegador: o proprio Flask serve o front
# ---------------------------------------------------------------------------
# Existe para o app rodar sem Electron -- e, com um tunel apontando para esta
# porta, ser aberto do celular.
#
# O build do Vite usa `base: "./"` (caminhos relativos), porque no Electron ele
# e carregado de file://. Isso obriga o app a viver numa **unica rota**: em
# /alguma/coisa os assets seriam procurados em /alguma/assets e nao existiriam.
# Por isso a pagina de legenda e `/?legenda=<id>`, e nao `/legenda/<id>`.


@app.route("/")
def web_index():
    if not (WEB_DIR / "index.html").exists():
        return jsonify(
            {
                "error": "Front nao construido",
                "como_resolver": "cd desktop && npm install && npm run build",
            }
        ), 404
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/assets/<path:filename>")
def web_assets(filename):
    return send_from_directory(WEB_DIR / "assets", filename)


@app.route("/favicon.ico")
def web_favicon():
    caminho = WEB_DIR / "favicon.ico"
    if not caminho.exists():
        return ("", 204)
    return send_from_directory(WEB_DIR, "favicon.ico")


# ---------------------------------------------------------------------------
# Fila de publicacao no TikTok (fase 5)
# ---------------------------------------------------------------------------
# Mesmo desenho da fila da Biblioteca: um worker so. Aqui o motivo nao e CPU e
# sim o TikTok -- o `inbox/video/init` aceita 6 requisicoes por minuto e por
# token, e enviar dois videos em paralelo estoura isso na primeira rajada.

PUBLISH_QUEUE = queue.Queue()
PUBLISH_WORKER_LOCK = threading.Lock()
PUBLISH_WORKER_STARTED = False

# Progresso de bytes vive em RAM, nao no SQLite: sao dezenas de atualizacoes por
# envio e nenhuma delas importa depois que o envio termina.
PUBLISH_PROGRESS = {}

# Quanto esperamos o TikTok processar antes de desistir. Nao e falha nossa se
# estourar -- o video pode aparecer nos rascunhos depois -- e a mensagem diz isso.
PUBLISH_STATUS_TIMEOUT = 300
PUBLISH_STATUS_INTERVALO = 3

# Os dois desfechos bons do TikTok, e eles NAO sao a mesma coisa:
#
#   SEND_TO_USER_INBOX -- a notificacao chegou na caixa de entrada do criador.
#                         O video existe, mas ainda nao foi publicado: falta o
#                         usuario tocar na notificacao e concluir no TikTok.
#   PUBLISH_COMPLETE   -- no fluxo de upload, significa que o usuario ja fez
#                         isso. E o unico estado que autoriza dizer "publicado".
#
# Tratar os dois como sucesso igual (como este codigo fazia) faz a interface
# prometer uma publicacao que nao aconteceu.
STATUS_INBOX = "SEND_TO_USER_INBOX"
STATUS_PUBLICADO = "PUBLISH_COMPLETE"


def _publish_fail(pub_id, mensagem):
    PUBLISH_PROGRESS.pop(pub_id, None)
    store.update_publication(pub_id, state="erro", error=str(mensagem)[:500])


def process_publication(pub_id):
    """Leva uma publicacao de 'fila' ate 'publicado' ou 'erro'."""
    pub = store.get_publication(pub_id)
    if not pub:
        return

    output = store.get_output(pub["output_id"])
    if not output:
        return _publish_fail(pub_id, "O video nao existe mais no catalogo.")

    caminho = OUTPUT_DIR / output["file"]
    if not caminho.exists():
        return _publish_fail(pub_id, "O arquivo do video nao esta mais em outputs/.")

    tamanho = caminho.stat().st_size

    try:
        token, conta = tiktok.valid_access_token()
    except tiktok.TikTokError as e:
        return _publish_fail(pub_id, e)

    store.update_publication(pub_id, state="enviando", error="")
    PUBLISH_PROGRESS[pub_id] = {"enviados": 0, "total": 1, "bytes": tamanho}

    try:
        publish_id, upload_url, chunk, total = tiktok.init_draft_upload(token, tamanho)
        store.update_publication(pub_id, publish_id=publish_id)
        PUBLISH_PROGRESS[pub_id] = {"enviados": 0, "total": total, "bytes": tamanho}

        def progresso(feitos, de):
            PUBLISH_PROGRESS[pub_id] = {
                "enviados": feitos, "total": de, "bytes": tamanho
            }

        tiktok.upload_file(
            upload_url, str(caminho), chunk, total, tamanho, progresso
        )
    except tiktok.TikTokError as e:
        return _publish_fail(pub_id, e)

    store.update_publication(pub_id, state="processando")

    limite = time.time() + PUBLISH_STATUS_TIMEOUT
    while time.time() < limite:
        time.sleep(PUBLISH_STATUS_INTERVALO)
        try:
            info = tiktok.publish_status(token, publish_id)
        except tiktok.TikTokError as e:
            return _publish_fail(pub_id, e)

        estado = (info.get("status") or "").upper()
        if estado in (STATUS_INBOX, STATUS_PUBLICADO):
            PUBLISH_PROGRESS.pop(pub_id, None)
            _aplicar_status(pub_id, output["id"], estado)
            return
        if estado == "FAILED":
            return _publish_fail(
                pub_id, info.get("fail_reason") or "O TikTok recusou o video."
            )

    _publish_fail(
        pub_id,
        "O TikTok ainda estava processando depois de 5 minutos. O video pode "
        "chegar na caixa de entrada mesmo assim -- confira no aplicativo antes "
        "de enviar de novo.",
    )


def _aplicar_status(pub_id, output_id, estado_tiktok):
    """Traduz o status do TikTok para o nosso, sem inventar publicacao."""
    if estado_tiktok == STATUS_PUBLICADO:
        store.update_publication(
            pub_id,
            state="publicado",
            error="",
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        store.update_output(output_id, status="publicado")
    else:
        store.update_publication(pub_id, state="aguardando", error="")
        store.update_output(output_id, status="aguardando")


def _sincronizar_publicacao(pub, token=None):
    """Pergunta ao TikTok como esta um envio e atualiza o registro.

    Existe porque o desfecho depende de uma acao que acontece **fora do app** --
    o usuario abrindo o TikTok e concluindo o post. Sem consultar de novo, o
    registro ficaria congelado em "aguardando" para sempre.
    """
    if not pub or not pub.get("publish_id"):
        return pub
    if pub["state"] not in ("aguardando", "processando"):
        return pub
    try:
        if token is None:
            token, _ = tiktok.valid_access_token()
        info = tiktok.publish_status(token, pub["publish_id"])
    except tiktok.TikTokError:
        # Consultar e melhor-esforco: uma conta trocada ou rede fora nao pode
        # transformar um envio bem-sucedido em erro.
        return pub

    estado = (info.get("status") or "").upper()
    if estado == "FAILED":
        _publish_fail(pub["id"], info.get("fail_reason") or "O TikTok recusou o video.")
    elif estado in (STATUS_INBOX, STATUS_PUBLICADO):
        _aplicar_status(pub["id"], pub["output_id"], estado)
    return store.get_publication(pub["id"])


@app.route("/api/publications/<pub_id>/refresh", methods=["POST"])
def api_publication_refresh(pub_id):
    pub = store.get_publication(pub_id)
    if not pub:
        return jsonify({"error": "Publicacao nao encontrada"}), 404
    return jsonify(_publication_view(_sincronizar_publicacao(pub)))


@app.route("/api/publications/refresh", methods=["POST"])
def api_publications_refresh():
    """Reconsulta todos os envios que ainda dependem de uma acao sua."""
    pendentes = [
        p for p in store.list_publications(limit=200)
        if p["state"] in ("aguardando", "processando") and p.get("publish_id")
    ]
    if not pendentes:
        return jsonify({"atualizadas": 0, "items": []})

    try:
        token, _ = tiktok.valid_access_token()
    except tiktok.TikTokError as e:
        return jsonify({"error": str(e)}), 400

    itens = [_publication_view(_sincronizar_publicacao(p, token)) for p in pendentes]
    return jsonify({"atualizadas": len(itens), "items": itens})


def _publish_worker():
    while True:
        pub_id = PUBLISH_QUEUE.get()
        try:
            process_publication(pub_id)
        except Exception as e:  # noqa: BLE001
            # Uma excecao inesperada nao pode matar o worker: a publicacao
            # seguinte ficaria na fila para sempre, sem ninguem para atende-la.
            _publish_fail(pub_id, f"Erro inesperado: {e}")
        finally:
            PUBLISH_QUEUE.task_done()


def _ensure_publish_worker():
    global PUBLISH_WORKER_STARTED
    with PUBLISH_WORKER_LOCK:
        if PUBLISH_WORKER_STARTED:
            return
        threading.Thread(
            target=_publish_worker, name="tiktok-publish-worker", daemon=True
        ).start()
        PUBLISH_WORKER_STARTED = True


def _publication_view(pub):
    """Publicacao + progresso de bytes, como a UI precisa ver."""
    if not pub:
        return None
    out = dict(pub)
    out["progresso"] = PUBLISH_PROGRESS.get(pub["id"])
    return out


@app.route("/api/outputs/<output_id>/publish", methods=["POST"])
def api_output_publish(output_id):
    output = store.get_output(output_id)
    if not output:
        return jsonify({"error": "Video nao encontrado"}), 404

    conta = store.active_account("tiktok")
    if not conta:
        return jsonify({"error": "Conecte a conta do TikTok em Ajustes."}), 400

    # Enviar de novo enquanto o anterior ainda esta em transito duplicaria o
    # video no TikTok sem que o usuario visse o primeiro chegar. Ja reenviar um
    # que esta "aguardando" e permitido de proposito: a notificacao pode nao ter
    # aparecido na caixa de entrada, e ai reenviar e a unica saida.
    for p in store.list_publications(limit=500):
        if p["output_id"] == output_id and p["state"] in store.PENDING_STATES:
            return jsonify({"error": "Este video ja esta sendo enviado."}), 409

    data = request.get_json(silent=True) or {}
    pub = store.add_publication(
        output_id=output_id,
        account_id=conta["id"],
        mode="draft",
        product_mode=str(data.get("product_mode") or "nenhum"),
        product_ids=data.get("product_ids") or [],
    )
    _ensure_publish_worker()
    PUBLISH_QUEUE.put(pub["id"])
    return jsonify(_publication_view(pub))


@app.route("/api/publications", methods=["GET"])
def api_publications_list():
    estado = request.args.get("state") or None
    itens = [_publication_view(p) for p in store.list_publications(state=estado)]
    return jsonify({"items": itens})


@app.route("/api/publications/<pub_id>", methods=["GET"])
def api_publication_get(pub_id):
    pub = store.get_publication(pub_id)
    if not pub:
        return jsonify({"error": "Publicacao nao encontrada"}), 404
    return jsonify(_publication_view(pub))


# ---------------------------------------------------------------------------
# Conta do TikTok (fase 4)
# ---------------------------------------------------------------------------
# O callback NAO e rota daqui: ele chega na porta fixa 43117, atendida por um
# listener descartavel em tiktok.py. Estas rotas so comandam o fluxo e contam
# como ele esta indo.


@app.route("/api/tiktok/account", methods=["GET"])
def api_tiktok_account():
    return jsonify(
        {
            "account": tiktok.current_account(),
            "cifra_do_sistema": secretbox.is_real_encryption(),
        }
    )


@app.route("/api/tiktok/account", methods=["DELETE"])
def api_tiktok_disconnect():
    return jsonify({"account": None, "removida": tiktok.disconnect()})


@app.route("/api/tiktok/connect", methods=["POST"])
def api_tiktok_connect():
    """Prepara o login e devolve a URL para o app abrir no navegador.

    `request.host_url` decide o caminho de volta: acessado do PC, o TikTok
    devolve no loopback; acessado pela URL publica, devolve na rota abaixo.
    """
    try:
        return jsonify(tiktok.start_connect(request.host_url))
    except tiktok.TikTokError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/tiktok/callback", methods=["GET"])
def api_tiktok_callback():
    """Retorno do TikTok quando o login comecou por um endereco publico.

    Fica atras da sessao de proposito. O TikTok redireciona o navegador para ca
    numa navegacao de primeiro nivel, e o cookie e SameSite=Lax -- ou seja, ele
    viaja. Deixar a rota publica so abriria uma porta a mais sem ganho nenhum;
    quem nao esta logado nao tinha como iniciar o fluxo.
    """
    resultado = tiktok.processar_callback(
        code=request.args.get("code", ""),
        state=request.args.get("state", ""),
        erro=request.args.get("error", ""),
        redirect_uri=tiktok.redirect_do_fluxo(),
    )
    return (
        tiktok.pagina_de_retorno(resultado),
        200,
        {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
    )


@app.route("/api/tiktok/connect", methods=["DELETE"])
def api_tiktok_connect_cancel():
    return jsonify(tiktok.cancel_connect())


@app.route("/api/tiktok/connect/status", methods=["GET"])
def api_tiktok_connect_status():
    """Polling da UI enquanto o usuario esta no navegador."""
    estado = tiktok.flow_status()
    if estado.get("state") == "conectado":
        estado["account"] = tiktok.current_account()
    return jsonify(estado)


def _porta_ja_ocupada(host, port):
    """Ha outra instancia servindo nesta porta?

    Existe porque o Windows deixa dois processos ligarem no mesmo endereco
    quando o socket usa SO_REUSEADDR -- que e o que o Werkzeug faz. O segundo
    sobe sem erro, as requisicoes vao para um ou para outro sem criterio, e o
    sintoma e absurdo: a interface nova conversando com o backend velho. Melhor
    recusar a subir e dizer o motivo.
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.7)
        try:
            s.connect((host if host != "0.0.0.0" else "127.0.0.1", port))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    # A porta pode vir do Electron (STUDIO_PORT) ou de PORT; default 5050 em dev.
    port = int(os.getenv("STUDIO_PORT") or os.getenv("PORT") or "5050")
    host = os.getenv("STUDIO_HOST", "127.0.0.1")

    if _porta_ja_ocupada(host, port):
        print(
            f"[StudioNative] ja existe algo servindo em {host}:{port}. "
            f"Feche a outra instancia ou use STUDIO_PORT para escolher outra "
            f"porta.",
            flush=True,
        )
        sys.exit(1)

    print(f"[StudioNative] backend em http://{host}:{port}", flush=True)

    # Servidor de producao. O `app.run()` do Flask e o servidor de
    # desenvolvimento do Werkzeug -- a propria documentacao dele diz para nao
    # usar em producao, e este app passa a atender pela internet.
    #
    # `threads=8` porque o trabalho pesado (render, upload para o TikTok) roda
    # em filas proprias, com worker unico; as requisicoes HTTP em si sao curtas.
    # Fora isso, waitress nao entrega arquivo grande com a mesma folga: o
    # `channel_timeout` alto existe para o upload de video da Biblioteca nao
    # morrer no meio.
    try:
        from waitress import serve

        serve(
            app,
            host=host,
            port=port,
            threads=8,
            channel_timeout=900,
            ident="StudioNative",
        )
    except ImportError:
        print(
            "[StudioNative] waitress ausente; caindo no servidor de "
            "desenvolvimento. NAO exponha isto a internet. "
            "Instale com: pip install waitress",
            flush=True,
        )
        app.run(host=host, port=port, debug=False, threaded=True)
