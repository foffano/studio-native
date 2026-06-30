import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory,
)
from PIL import Image, ImageDraw, ImageFont

from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

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
STATIC_DIR = resource_path("static")
FONTS_DIR = resource_path("fonts")

USER_DATA_DIR = user_data_dir()
CONFIG_PATH = USER_DATA_DIR / "config.json"
UPLOAD_DIR = USER_DATA_DIR / "uploads"
OUTPUT_DIR = USER_DATA_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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


@app.after_request
def _add_cors_headers(resp):
    # O Electron carrega o React de outra origem (vite dev / file://) e fala
    # com o backend local via HTTP, entao habilitamos CORS de forma ampla
    # (o servidor so escuta em 127.0.0.1).
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# Armazenamento simples de jobs em memoria
JOBS = {}
JOBS_LOCK = threading.Lock()


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


def generate_phrases(n, theme):
    """Chama a OpenRouter SOMENTE com texto e retorna uma lista de n frases.

    O video NUNCA e enviado para a API - apenas o prompt de texto abaixo.
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
        "Gere frases curtas, impactantes e em portugues do Brasil, prontas para serem "
        "sobrepostas no video. Pode usar 1 ou 2 emojis quando fizer sentido. "
        "Cada frase deve ter no maximo 120 caracteres."
    )

    user_prompt = (
        f"{theme_part}\n\n"
        f"Gere exatamente {n} frases DIFERENTES entre si.\n"
        "Responda APENAS com um JSON valido no formato: "
        '{"frases": ["frase 1", "frase 2", ...]}. '
        "Nao inclua explicacoes, numeracao ou texto fora do JSON."
    )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.9,
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
        raise RuntimeError(
            f"Erro da OpenRouter ({resp.status_code}): {resp.text[:300]}"
        )

    content = resp.json()["choices"][0]["message"]["content"]
    phrases = parse_phrases(content, n)
    if not phrases:
        raise RuntimeError("A IA nao retornou frases validas.")
    return phrases[:n]


def parse_phrases(content, n):
    """Extrai a lista de frases da resposta da IA, de forma tolerante."""
    content = content.strip()
    # Tenta extrair bloco JSON
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            frases = data.get("frases") or data.get("phrases")
            if isinstance(frases, list):
                return [str(f).strip() for f in frases if str(f).strip()]
        except json.JSONDecodeError:
            pass
    # Fallback: divide por linhas
    lines = [
        re.sub(r"^\s*[\d\-\.\)\"]+\s*", "", ln).strip().strip('"')
        for ln in content.splitlines()
        if ln.strip()
    ]
    return [ln for ln in lines if ln][:n]


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


def generate_overlay_and_speech(n, theme, video_duration):
    """Gera n pares coerentes (overlay curto na tela + speech para narracao),
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
        "(ritmo de fala natural). NAO use emojis na speech.\n\n"
        "Responda APENAS com JSON valido no formato: "
        '{"itens": [{"overlay": "...", "speech": "..."}, ...]}. '
        "Sem explicacoes nem texto fora do JSON."
    )

    content = _openrouter_chat(system_prompt, user_prompt)
    items = parse_overlay_speech(content, n)
    if not items:
        raise RuntimeError("A IA nao retornou overlay/speech validos.")
    return items[:n]


def parse_overlay_speech(content, n):
    """Extrai a lista [{overlay, speech}] da resposta da IA, de forma tolerante."""
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


def process_job(job_id, src_path, num, theme, options, audio_opts=None):
    norm_path = UPLOAD_DIR / f"{job_id}_norm.mp4"
    audio_files = []
    try:
        set_job(
            job_id,
            status="normalizing",
            message="Normalizando o video (ffmpeg)...",
            progress=0,
        )
        normalize_video(src_path, norm_path)

        audio_mode = bool(audio_opts and audio_opts.get("enabled"))

        if audio_mode:
            video_dur = media_duration(norm_path)
            set_job(
                job_id,
                status="generating_text",
                message="Gerando roteiro (overlay + narracao) com a IA...",
            )
            audio_theme = audio_opts.get("theme") or theme
            items = generate_overlay_and_speech(num, audio_theme, video_dur)

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
                results.append(
                    {
                        "phrase": item["overlay"],
                        "speech": item["speech"],
                        "file": out_name,
                    }
                )
                set_job(job_id, results=results, progress=int(i / total * 100))
        else:
            set_job(
                job_id,
                status="generating_text",
                message="Gerando frases com a IA...",
            )
            phrases = generate_phrases(num, theme)

            results = []
            total = len(phrases)
            for i, phrase in enumerate(phrases, start=1):
                set_job(
                    job_id,
                    status="rendering",
                    message=f"Renderizando video {i} de {total}...",
                    progress=int((i - 1) / total * 100),
                )
                out_name = f"{job_id}_{i}.mp4"
                out_path = OUTPUT_DIR / out_name
                render_video(norm_path, phrase, out_path, options)
                results.append({"phrase": phrase, "file": out_name})
                set_job(job_id, results=results, progress=int(i / total * 100))

        set_job(
            job_id,
            status="done",
            message="Concluido!",
            progress=100,
            results=results,
        )
    except Exception as e:  # noqa: BLE001
        set_job(job_id, status="error", message=str(e))
    finally:
        for p in [src_path, norm_path, *audio_files]:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/<path:_unused>", methods=["OPTIONS"])
def api_preflight(_unused):
    return ("", 204)


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "app": "Studio Native"})


@app.route("/api/generate", methods=["POST"])
def api_generate():
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
    src_path = UPLOAD_DIR / f"{job_id}{ext}"
    file.save(str(src_path))

    set_job(job_id, status="queued", message="Na fila...", progress=0, results=[])

    thread = threading.Thread(
        target=process_job,
        args=(job_id, src_path, num, theme, options, audio_opts),
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


if __name__ == "__main__":
    # A porta pode vir do Electron (STUDIO_PORT) ou de PORT; default 5050 em dev.
    port = int(os.getenv("STUDIO_PORT") or os.getenv("PORT") or "5050")
    host = os.getenv("STUDIO_HOST", "127.0.0.1")
    print(f"[StudioNative] backend em http://{host}:{port}", flush=True)
    app.run(host=host, port=port, debug=False, threaded=True)
