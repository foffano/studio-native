"""Legenda do post e hashtags.

A IA sugere, mas quem manda e o codigo: o limite de 5 hashtags, o tamanho da
legenda e o formato das tags sao aplicados aqui, nunca confiando no prompt.
Tambem ha fallback deterministico para quando a IA falhar - o usuario nunca fica
sem legenda.
"""

import re
import unicodedata

MAX_HASHTAGS = 5
MAX_TAG_LEN = 24
MAX_CAPTION_LEN = 150

# Tags genericas que quase sempre vem da IA; usadas so para completar quando
# sobrar espaco, nunca no lugar de uma tag especifica do tema.
FILLER_TAGS = ["fyp", "viral", "paravoce"]

_TAG_IN_TEXT = re.compile(r"#\s*([^\s#]+)")
_NON_TAG_CHARS = re.compile(r"[^a-z0-9_]")


def slug_tag(raw):
    """Transforma um texto solto numa hashtag valida (sem o '#')."""
    text = str(raw or "").strip().lstrip("#")
    if not text:
        return ""
    # Remove acentos: "receitas rapidas" -> "receitasrapidas"
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower().replace(" ", "").replace("-", "")
    text = _NON_TAG_CHARS.sub("", text)
    return text[:MAX_TAG_LEN]


def normalize_hashtags(items, limit=MAX_HASHTAGS):
    """Sanitiza e corta a lista de hashtags. O corte em 5 mora aqui."""
    out = []
    if isinstance(items, str):
        items = _TAG_IN_TEXT.findall(items) or items.split()
    for item in items or []:
        tag = slug_tag(item)
        if not tag or tag in out:
            continue
        out.append(tag)
        if len(out) >= limit:
            break
    return out


def split_trailing_hashtags(text):
    """Separa as hashtags que a IA costuma colar no fim da legenda.

    Devolve (legenda_sem_tags, tags_encontradas).
    """
    raw = str(text or "").strip()
    if not raw:
        return "", []
    found = _TAG_IN_TEXT.findall(raw)
    clean = _TAG_IN_TEXT.sub("", raw)
    clean = re.sub(r"\s+", " ", clean).strip(" \t\n-|·,;")
    return clean, found


def clean_caption(text, limit=MAX_CAPTION_LEN):
    """Normaliza espacos e corta no limite sem partir palavra ao meio."""
    caption = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(caption) <= limit:
        return caption
    cut = caption[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" .,;:-") + "…"


def fallback_caption(phrase, theme=""):
    """Legenda quando a IA nao devolveu nenhuma: a propria frase da tela."""
    base = clean_caption(phrase) or clean_caption(theme)
    return base


def fallback_hashtags(theme="", extra_tags=None, limit=MAX_HASHTAGS):
    """Hashtags derivadas do tema digitado e das tags do video-fonte."""
    candidates = []
    for word in re.split(r"[\s,;/]+", str(theme or "")):
        if len(word) >= 4:
            candidates.append(word)
    candidates.extend(extra_tags or [])
    tags = normalize_hashtags(candidates, limit=limit)
    for filler in FILLER_TAGS:
        if len(tags) >= limit:
            break
        if filler not in tags:
            tags.append(filler)
    return tags[:limit]


def finalize(caption_raw, hashtags_raw, phrase="", theme="", extra_tags=None):
    """Aplica todas as regras de uma vez e devolve (caption, hashtags).

    Hashtags que a IA colou no fim da legenda sao movidas para a lista em vez de
    ficarem duplicadas nos dois lugares.
    """
    caption, inline_tags = split_trailing_hashtags(caption_raw)
    tags = normalize_hashtags(list(hashtags_raw or []) + inline_tags)

    if not caption:
        caption = fallback_caption(phrase, theme)
    caption = clean_caption(caption)

    if not tags:
        tags = fallback_hashtags(theme, extra_tags)

    return caption, tags
