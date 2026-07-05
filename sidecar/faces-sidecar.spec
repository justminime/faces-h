# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# We only run InsightFace's detection + recognition models (see allowed_modules
# in ml/insightface_recognizer.py). PyInstaller's static analysis already bundles
# the directly-imported deps (onnxruntime, cv2, numpy, insightface). The one gap
# is scikit-image: insightface aligns faces via skimage.transform, and skimage
# uses lazy_loader so its submodules are invisible to static analysis. We collect
# just skimage's submodules + data files (and its scipy backend) — NOT the whole
# scientific stack via collect_all, which previously bloated the onefile bundle
# so much that extraction blew past the sidecar startup timeout.
_ml_hiddenimports = collect_submodules("skimage") + collect_submodules("scipy")
_ml_datas = collect_data_files("skimage")

a = Analysis(
    ["main.py"],
    pathex=[str(Path(".").resolve())],
    binaries=[],
    datas=_ml_datas,
    hiddenimports=_ml_hiddenimports + [
        # uvicorn dynamic imports that PyInstaller misses
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.loops.uvloop",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        # FastAPI / starlette
        "starlette.routing",
        "starlette.middleware.cors",
        # anyio backends
        "anyio._backends._asyncio",
        "anyio._backends._trio",
        # parent-process watchdog (#119) — imported lazily in main._parent_alive
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # InsightFace runs on onnxruntime, not torch/tensorflow, so keep these
        # heavy frameworks out of the bundle to limit size and Defender scan time.
        "torch",
        "tensorflow",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="faces-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX disabled: Windows Defender must decompress UPX-packed files before
    # scanning, which adds 60-90 s on first run after an upgrade.  Without UPX
    # the binary is larger but Defender scans it in < 10 s.
    upx=False,
    upx_exclude=[],
    # Fixed extraction dir so PyInstaller reuses cached files on subsequent
    # runs of the same version instead of creating a new random temp dir each
    # time.  The NSIS installer sets FACES_H_RUNTIME_DIR to the install path.
    runtime_tmpdir=None,
    console=False,          # no console window in production
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
