"""Baixa binarios estaticos do ffmpeg/ffprobe para a pasta `bin/`.

Esses binarios sao empacotados pelo PyInstaller (ver studio_native_backend.spec)
para que o usuario final NAO precise ter o ffmpeg instalado.

Uso:
    python tools/fetch_ffmpeg.py

Por padrao baixa builds do gyan.dev (Windows x64). Em outros SOs, instale o
ffmpeg manualmente ou ajuste as URLs abaixo.
"""
import io
import os
import platform
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin"

# Build essencial (inclui ffmpeg.exe e ffprobe.exe).
WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _download(url):
    print(f"Baixando {url} ...")
    req = Request(url, headers={"User-Agent": "StudioNative-build"})
    with urlopen(req, timeout=120) as resp:  # noqa: S310
        return resp.read()


def fetch_windows():
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    raw = _download(WIN_URL)
    z = zipfile.ZipFile(io.BytesIO(raw))
    wanted = ("ffmpeg.exe", "ffprobe.exe")
    extracted = {}
    for name in z.namelist():
        base = os.path.basename(name)
        if base in wanted and base not in extracted:
            with z.open(name) as src:
                data = src.read()
            (BIN_DIR / base).write_bytes(data)
            extracted[base] = len(data)
            print(f"  -> bin/{base} ({len(data)} bytes)")
    missing = [w for w in wanted if w not in extracted]
    if missing:
        raise SystemExit(f"Nao encontrei no zip: {missing}")
    print("OK: ffmpeg/ffprobe prontos em bin/")


def main():
    system = platform.system().lower()
    if system == "windows":
        fetch_windows()
    else:
        print(
            "Este script baixa binarios do Windows. Em "
            f"{system}, instale ffmpeg/ffprobe e copie para bin/ manualmente, "
            "ou confie no ffmpeg do PATH."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
