"""Cifragem dos tokens do TikTok em repouso.

O banco fica em `%APPDATA%/StudioNative/`, legivel por qualquer processo que
rode como o usuario. Um access token do TikTok em texto puro ali e uma conta
sequestravel por qualquer coisa que leia o disco.

**No Windows usamos DPAPI** (`CryptProtectData`), via ctypes: sem dependencia
nova, sem chave para guardar, e o texto cifrado so volta a ser legivel pela
mesma conta de usuario do Windows. Copiar o arquivo para outra maquina nao
adianta.

Fora do Windows nao existe equivalente sem trazer `cryptography` para dentro do
PyInstaller. La o segredo e apenas *ofuscado* com XOR sobre uma chave em
arquivo com permissao 0600 — e a funcao diz isso na cara, em vez de fingir
seguranca que nao tem. O app e Windows-first; se um dia virar multiplataforma
de verdade, e aqui que entra o Keychain / libsecret.
"""

import base64
import ctypes
import hashlib
import os
import sys
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# Prefixos para o formato saber se ler de volta com DPAPI ou com o fallback.
# Sem isso, um banco copiado entre plataformas viraria lixo silencioso.
_DPAPI = "dpapi:"
_XOR = "xor:"


# ---------------------------------------------------------------------------
# Windows — DPAPI
# ---------------------------------------------------------------------------
if IS_WINDOWS:

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    # Sem esta flag o DPAPI pode abrir dialogo do Windows. Num backend sem
    # janela isso trava o processo para sempre.
    _UI_FORBIDDEN = 0x1

    def _blob(data: bytes) -> _Blob:
        buf = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _take(blob: _Blob) -> bytes:
        out = ctypes.string_at(blob.pbData, blob.cbData)
        _kernel32.LocalFree(blob.pbData)
        return out

    def _dpapi_protect(raw: bytes) -> bytes:
        out = _Blob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(_blob(raw)), None, None, None, None, _UI_FORBIDDEN,
            ctypes.byref(out),
        )
        if not ok:
            raise OSError(ctypes.get_last_error() or "CryptProtectData falhou")
        return _take(out)

    def _dpapi_unprotect(enc: bytes) -> bytes:
        out = _Blob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(_blob(enc)), None, None, None, None, _UI_FORBIDDEN,
            ctypes.byref(out),
        )
        if not ok:
            raise OSError(ctypes.get_last_error() or "CryptUnprotectData falhou")
        return _take(out)


# ---------------------------------------------------------------------------
# Fora do Windows — ofuscacao declarada
# ---------------------------------------------------------------------------
_KEY_CACHE = None


def _fallback_key(data_dir: Path) -> bytes:
    """Chave do XOR, em arquivo so-do-dono. Isto NAO e cifra de verdade."""
    global _KEY_CACHE
    if _KEY_CACHE is not None:
        return _KEY_CACHE
    path = data_dir / ".token-key"
    if path.exists():
        _KEY_CACHE = path.read_bytes()
    else:
        _KEY_CACHE = os.urandom(32)
        path.write_bytes(_KEY_CACHE)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return _KEY_CACHE


def _xor(raw: bytes, key: bytes) -> bytes:
    # Chave esticada por SHA-256 em contador, para nao repetir o keystream em
    # segredos maiores que a chave.
    stream = bytearray()
    counter = 0
    while len(stream) < len(raw):
        stream += hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(a ^ b for a, b in zip(raw, stream))


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
_DATA_DIR = Path(".")


def init_secretbox(data_dir):
    """Define onde mora a chave do fallback. No Windows nao faz diferenca."""
    global _DATA_DIR
    _DATA_DIR = Path(data_dir)


def encrypt(plain: str) -> str:
    """Cifra um segredo. Devolve texto ASCII pronto para o SQLite."""
    if not plain:
        return ""
    raw = plain.encode("utf-8")
    if IS_WINDOWS:
        return _DPAPI + base64.b64encode(_dpapi_protect(raw)).decode("ascii")
    key = _fallback_key(_DATA_DIR)
    return _XOR + base64.b64encode(_xor(raw, key)).decode("ascii")


def decrypt(blob: str) -> str:
    """Decifra. Devolve "" se o segredo nao for legivel nesta maquina.

    Falhar em silencio e proposital: um token que nao decifra (banco copiado de
    outro usuario do Windows, perfil recriado) tem que se comportar como token
    ausente, para o app pedir login de novo em vez de estourar na cara.
    """
    if not blob:
        return ""
    try:
        if blob.startswith(_DPAPI):
            if not IS_WINDOWS:
                return ""
            return _dpapi_unprotect(base64.b64decode(blob[len(_DPAPI):])).decode("utf-8")
        if blob.startswith(_XOR):
            key = _fallback_key(_DATA_DIR)
            return _xor(base64.b64decode(blob[len(_XOR):]), key).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def is_real_encryption() -> bool:
    """A UI usa isto para nao prometer o que a plataforma nao entrega."""
    return IS_WINDOWS
