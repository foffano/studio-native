"""Autenticacao do Studio Native.

Ate a versao 1.2.x o app nao tinha senha, e isso estava certo: ele so escutava
em 127.0.0.1, entao a unica porta era a propria maquina. Ao ser exposto por um
tunel, a premissa cai e a protecao precisa existir no codigo.

## O que este modulo protege, e o que nao protege

Ele protege o **acesso HTTP**. Nao protege os tokens do TikTok em repouso --
disso cuida `secretbox.py`, com o DPAPI do Windows.

Sao camadas separadas de proposito, e vale explicar porque a ideia de unificar e
tentadora: derivar a chave de cifragem dos tokens a partir da senha do admin
seria mais elegante, com um segredo so. Mas o backend roda como servico e sobe
no boot, sem ninguem para digitar senha -- e precisa decifrar os tokens para
renovar a sessao do TikTok sozinho. Com a chave presa a senha, ele subiria
inutil.

## Escolhas

- **scrypt** (`hashlib`, biblioteca padrao) para o hash da senha. Custo de
  memoria alto de proposito: e o que torna ataque por GPU caro.
- **Sessao em cookie assinado** do proprio Flask (itsdangerous, ja vem junto).
  Sem servidor de sessao, sem dependencia nova.
- **`hmac.compare_digest`** em toda comparacao de segredo, para o tempo de
  resposta nao contar quantos caracteres bateram.
- **Atraso progressivo por IP** nas tentativas. Nao e rate limit de verdade --
  isso pertence ao Cloudflare -- mas transforma forca bruta de horas em anos.
"""

import hashlib
import hmac
import os
import secrets
import threading
import time

# Parametros do scrypt. n=2**15 leva ~100ms nesta classe de maquina: imperceptivel
# num login, proibitivo em bilhoes de tentativas.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 64

# n=2**15 com r=8 pede 128*n*r = 32 MB, que e exatamente o teto padrao do
# OpenSSL -- e ele recusa com "memory limit exceeded". Subimos o teto em vez de
# baixar o `n`: reduzir o parametro seria enfraquecer o hash para contornar um
# limite de configuracao.
SCRYPT_MAXMEM = 96 * 1024 * 1024

# Depois de 5 erros o IP espera. O atraso dobra e satura em 5 minutos.
TENTATIVAS_LIVRES = 5
ATRASO_BASE = 2
ATRASO_MAXIMO = 300

_LOCK = threading.Lock()
_FALHAS = {}  # ip -> {"n": int, "ate": timestamp}


# ---------------------------------------------------------------------------
# Senha
# ---------------------------------------------------------------------------

def gerar_hash(senha):
    """Devolve 'scrypt$<sal_hex>$<hash_hex>' para guardar no config.json."""
    if not senha:
        raise ValueError("senha vazia")
    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        senha.encode("utf-8"), salt=sal,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${sal.hex()}${dk.hex()}"


def conferir_senha(senha, guardado):
    """Confere a senha contra o hash guardado, em tempo constante."""
    if not senha or not guardado:
        return False
    try:
        algoritmo, sal_hex, esperado_hex = guardado.split("$", 2)
    except ValueError:
        return False
    if algoritmo != "scrypt":
        return False
    try:
        dk = hashlib.scrypt(
            senha.encode("utf-8"), salt=bytes.fromhex(sal_hex),
            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN,
            maxmem=SCRYPT_MAXMEM,
        )
    except ValueError:
        return False
    return hmac.compare_digest(dk.hex(), esperado_hex)


def forca_da_senha(senha):
    """Devolve o motivo de recusa, ou '' se a senha serve.

    O minimo e 10 caracteres. Regras de composicao (maiuscula, simbolo) nao
    entram: elas empurram para senhas curtas e decoraveis como "Senha@1", que
    sao piores que uma frase longa.
    """
    if not senha or len(senha) < 10:
        return "A senha precisa de pelo menos 10 caracteres."
    if senha.lower() in ("1234567890", "senha12345", "password12"):
        return "Essa senha e obvia demais."
    return ""


# ---------------------------------------------------------------------------
# Freio de forca bruta
# ---------------------------------------------------------------------------

def bloqueado_ate(ip):
    """Segundos restantes de bloqueio para este IP (0 se liberado)."""
    with _LOCK:
        reg = _FALHAS.get(ip)
        if not reg:
            return 0
        return max(0, int(reg["ate"] - time.time()))


def registrar_falha(ip):
    with _LOCK:
        reg = _FALHAS.setdefault(ip, {"n": 0, "ate": 0})
        reg["n"] += 1
        if reg["n"] > TENTATIVAS_LIVRES:
            excedente = reg["n"] - TENTATIVAS_LIVRES
            atraso = min(ATRASO_MAXIMO, ATRASO_BASE * (2 ** (excedente - 1)))
            reg["ate"] = time.time() + atraso


def limpar_falhas(ip):
    with _LOCK:
        _FALHAS.pop(ip, None)


# ---------------------------------------------------------------------------
# Chave de assinatura da sessao
# ---------------------------------------------------------------------------

def obter_secret_key(config, salvar):
    """Chave que assina o cookie de sessao, criada uma vez e persistida.

    Precisa sobreviver a reinicios: gerada a cada boot, todo mundo seria
    deslogado sempre que o servico reiniciasse.
    """
    chave = str(config.get("SESSION_SECRET") or "")
    if len(chave) >= 43:
        return chave
    chave = secrets.token_urlsafe(48)
    config["SESSION_SECRET"] = chave
    salvar(config)
    return chave


def ip_do_pedido(request):
    """IP real do cliente, respeitando o cabecalho do Cloudflare.

    Atras do tunel, `remote_addr` e sempre 127.0.0.1 -- o freio de forca bruta
    trataria o mundo inteiro como um IP so. `CF-Connecting-IP` e posto pela
    Cloudflare e nao pode ser forjado por quem passa por ela; so confiamos nele
    quando a conexao vem do loopback, que e por onde o tunel entrega.
    """
    if request.remote_addr in ("127.0.0.1", "::1"):
        vindo_da_cloudflare = request.headers.get("CF-Connecting-IP")
        if vindo_da_cloudflare:
            return vindo_da_cloudflare.strip()[:45]
    return request.remote_addr or "desconhecido"
