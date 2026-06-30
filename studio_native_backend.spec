# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec do backend "Studio Native" (sidecar do Electron).

Gera uma pasta dist/StudioNativeBackend/ com o executavel e todos os recursos
(fonts, ffmpeg/ffprobe). O Electron empacota essa pasta em
resources/backend e a spawna em producao.

Build:
    pip install -r requirements.txt
    python tools/fetch_ffmpeg.py        # baixa ffmpeg/ffprobe para bin/
    pyinstaller studio_native_backend.spec --noconfirm
"""
import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Coleta pacotes que precisam de dados/binarios proprios.
for pkg in ("moviepy", "imageio", "imageio_ffmpeg"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] collect_all falhou para {pkg}: {exc}")

# Assets do backend.
datas += [("fonts", "fonts")]

# ffmpeg/ffprobe empacotados (se baixados em bin/).
if os.path.isdir("bin"):
    for fn in os.listdir("bin"):
        binaries.append((os.path.join("bin", fn), "bin"))
else:
    print("[spec] AVISO: pasta bin/ ausente; rode tools/fetch_ffmpeg.py para "
          "empacotar ffmpeg/ffprobe (senao o app dependera do ffmpeg do PATH).")

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["dotenv"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudioNativeBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StudioNativeBackend",
)
