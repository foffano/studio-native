"""Cifragem dos tokens do TikTok em repouso.

O banco fica na pasta de dados do app, legivel por qualquer processo que rode
como o usuario. Um access token do TikTok em texto puro ali e uma conta
sequestravel por qualquer coisa que leia o disco.

**No Windows usamos DPAPI** (`CryptProtectData`), via ctypes: sem dependencia
nova, sem chave para guardar, e o texto cifrado so volta a ser legivel pela
mesma conta de usuario do Windows. Copiar o arquivo para outra maquina nao
adianta.

**Fora do Windows usamos AES-256-GCM** (pacote `cryptography`). O que protege
de verdade e onde a chave mora, e ela e procurada nesta ordem:

1. `$CREDENTIALS_DIRECTORY/token-key` -- o `LoadCredential=` do systemd. O
   arquivo original pode ser so do root: o systemd entrega ao servico uma copia
   que so ele le, fora da pasta de dados.
2. `STUDIO_TOKEN_KEY_FILE` -- caminho explicito, para systemd antigo (sem
   LoadCredential) ou outro supervisor.
3. `.token-key` dentro da pasta de dados, criada na hora. E cifra de verdade,
   mas com a chave ao lado do banco: um backup ou snapshot da pasta leva as
   duas coisas juntas. A interface avisa quando e este o caso.

Chave configurada tem que abrir. Se `STUDIO_TOKEN_KEY_FILE` aponta para um
arquivo ilegivel, o app nao sobe: cair em silencio na chave local cifraria os
tokens novos com a chave errada, e o problema so apareceria no dia em que a
configuracao fosse corrigida.

Sem `cryptography` instalado sobra o formato antigo, XOR sobre a chave local --
*ofuscacao*, e declarada como tal. Tokens `xor:` antigos continuam legiveis; os
novos saem em `aesgcm:`.
"""

import base64
import binascii
import ctypes
import hashlib
import os
import sys
import threading
from ctypes import wintypes
from pathlib import Path

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # no Windows o pacote nem e instalado
    AESGCM = None
    InvalidTag = Exception

IS_WINDOWS = os.name == "nt"

# Prefixos para o formato saber como ler de volta.
# Sem isso, um banco copiado entre plataformas viraria lixo silencioso.
_DPAPI = "dpapi:"
_AES = "aesgcm:"
_XOR = "xor:"

# Dado associado do GCM: amarra o texto cifrado a esta finalidade.
_AAD = b"studio-native:tiktok-token:v1"
_NONCE_BYTES = 12


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
# Chaves fora do Windows
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()
_DATA_DIR = Path(".")
_LOCAL_KEY = None
_EXTERNAL = (None, None)
_EXTERNAL_RESOLVED = False


def _local_key_path() -> Path:
    return _DATA_DIR / ".token-key"


def _fallback_key() -> bytes:
    """Chave local, em arquivo so-do-dono ao lado dos dados. Criada se faltar."""
    global _LOCAL_KEY
    with _LOCK:
        if _LOCAL_KEY is not None:
            return _LOCAL_KEY
        path = _local_key_path()
        try:
            # O_EXCL + 0600 ja na criacao: o arquivo nunca existe com permissao
            # aberta, nem por um instante.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            _LOCAL_KEY = path.read_bytes()
            return _LOCAL_KEY
        chave = os.urandom(32)
        with os.fdopen(fd, "wb") as f:
            f.write(chave)
        _LOCAL_KEY = chave
        return _LOCAL_KEY


def _read_key_file(path) -> bytes:
    """32 bytes de chave: crus, em base64 ou em hex (`openssl rand -hex 32`)."""
    raw = Path(path).read_bytes()
    if len(raw) == 32:
        return raw
    texto = raw.strip()
    if len(texto) == 64:
        try:
            return bytes.fromhex(texto.decode("ascii"))
        except ValueError:
            pass
    try:
        decodificado = base64.b64decode(texto, validate=True)
    except (ValueError, binascii.Error):
        decodificado = b""
    if len(decodificado) == 32:
        return decodificado
    raise ValueError(
        f"A chave dos tokens em {path} precisa ter 32 bytes (crus, em base64 ou "
        "em hex). Gere uma com: head -c 32 /dev/urandom > arquivo"
    )


def _resolve_external_key():
    credenciais = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if credenciais:
        caminho = Path(credenciais) / "token-key"
        if caminho.exists():
            return _read_key_file(caminho), "systemd"
    caminho = os.environ.get("STUDIO_TOKEN_KEY_FILE", "").strip()
    if caminho:
        return _read_key_file(caminho), "arquivo"
    return None, None


def _external_key():
    """(chave, origem) vinda de fora da pasta de dados, ou (None, None)."""
    global _EXTERNAL, _EXTERNAL_RESOLVED
    with _LOCK:
        if not _EXTERNAL_RESOLVED:
            _EXTERNAL = _resolve_external_key()
            _EXTERNAL_RESOLVED = True
        return _EXTERNAL


def _derive(material: bytes) -> bytes:
    """Chave AES a partir do material guardado, com separacao de dominio.

    A chave local e a mesma que o formato XOR antigo usa. Derivar, em vez de
    usar os bytes crus, evita que um segredo sirva a dois esquemas diferentes.
    """
    return hashlib.sha256(b"studio-native/aesgcm/v1\x00" + material).digest()


def _encryption_key() -> bytes:
    """Chave para cifrar agora: a externa quando existe, senao a local."""
    externa, _ = _external_key()
    if externa is not None:
        return _derive(externa)
    return _derive(_fallback_key())


def _candidate_keys():
    """Chaves que podem ter cifrado um token, da preferida para a antiga.

    A local entra mesmo com chave externa configurada: um token cifrado antes de
    a chave externa existir continua legivel, e o app o recifra com a externa
    na proxima renovacao da sessao.
    """
    externa, _ = _external_key()
    if externa is not None:
        yield _derive(externa)
    if _LOCAL_KEY is not None or _local_key_path().exists():
        yield _derive(_fallback_key())


def _aes_encrypt(raw: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    return nonce + AESGCM(_encryption_key()).encrypt(nonce, raw, _AAD)


def _aes_decrypt(blob: bytes) -> bytes:
    nonce, cifrado = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    for chave in _candidate_keys():
        try:
            return AESGCM(chave).decrypt(nonce, cifrado, _AAD)
        except InvalidTag:
            continue
    raise ValueError("nenhuma chave disponivel abre este token")


def _xor(raw: bytes, key: bytes) -> bytes:
    # Chave esticada por SHA-256 em contador, para nao repetir o keystream em
    # segredos maiores que a chave. Formato antigo: so leitura, fora do Windows.
    stream = bytearray()
    counter = 0
    while len(stream) < len(raw):
        stream += hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(a ^ b for a, b in zip(raw, stream))


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def init_secretbox(data_dir):
    """Define a pasta de dados e confere a chave configurada.

    Levanta excecao se `STUDIO_TOKEN_KEY_FILE` (ou a credencial do systemd)
    existir e nao servir -- de proposito, no boot. Ver o docstring do modulo.
    """
    global _DATA_DIR, _LOCAL_KEY, _EXTERNAL, _EXTERNAL_RESOLVED
    with _LOCK:
        _DATA_DIR = Path(data_dir)
        _LOCAL_KEY = None
        _EXTERNAL, _EXTERNAL_RESOLVED = (None, None), False
    if not IS_WINDOWS and AESGCM is not None:
        _external_key()


def encrypt(plain: str) -> str:
    """Cifra um segredo. Devolve texto ASCII pronto para o SQLite."""
    if not plain:
        return ""
    raw = plain.encode("utf-8")
    if IS_WINDOWS:
        return _DPAPI + base64.b64encode(_dpapi_protect(raw)).decode("ascii")
    if AESGCM is not None:
        return _AES + base64.b64encode(_aes_encrypt(raw)).decode("ascii")
    return _XOR + base64.b64encode(_xor(raw, _fallback_key())).decode("ascii")


def decrypt(blob: str) -> str:
    """Decifra. Devolve "" se o segredo nao for legivel nesta maquina.

    Falhar em silencio e proposital: um token que nao decifra (banco copiado de
    outro usuario do Windows, do Windows para o Linux, perfil recriado) tem que
    se comportar como token ausente, para o app pedir login de novo em vez de
    estourar na cara.
    """
    if not blob:
        return ""
    try:
        if blob.startswith(_DPAPI):
            if not IS_WINDOWS:
                return ""
            return _dpapi_unprotect(base64.b64decode(blob[len(_DPAPI):])).decode("utf-8")
        if blob.startswith(_AES):
            if AESGCM is None:
                return ""
            return _aes_decrypt(base64.b64decode(blob[len(_AES):])).decode("utf-8")
        if blob.startswith(_XOR):
            key = _fallback_key()
            return _xor(base64.b64decode(blob[len(_XOR):]), key).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def protection() -> str:
    """Como os tokens ficam guardados nesta maquina.

    - `dpapi`: Windows, amarrado a conta do usuario;
    - `aes`: AES-GCM com a chave fora da pasta de dados;
    - `aes_chave_local`: AES-GCM, mas com a chave ao lado do banco;
    - `xor`: so ofuscacao, porque falta o pacote `cryptography`.
    """
    if IS_WINDOWS:
        return "dpapi"
    if AESGCM is None:
        return "xor"
    externa, _ = _external_key()
    return "aes" if externa is not None else "aes_chave_local"


def is_real_encryption() -> bool:
    """A UI usa isto para nao prometer o que a plataforma nao entrega."""
    return protection() in ("dpapi", "aes")
