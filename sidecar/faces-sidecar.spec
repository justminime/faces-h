# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# InsightFace loads its detection/recognition handlers and reads packaged data
# files dynamically, and it leans on native extensions in cv2 / scikit-image /
# scipy / onnx(runtime) during inference. PyInstaller's static analysis misses
# these, so a frozen build can import InsightFace and load models yet still
# return None from detection at runtime. collect_all pulls each package's
# submodules, data files, and binaries so the frozen sidecar matches a normal
# venv. (Resolves the "bundle InsightFace" TODO from issue #7.)
_ml_datas = []
_ml_binaries = []
_ml_hiddenimports = []
for _pkg in ("insightface", "cv2", "skimage", "scipy", "onnx", "onnxruntime", "sklearn"):
    try:
        _d, _b, _h = collect_all(_pkg)
    except Exception:
        # Optional/transitive package not installed in this build env — skip it
        # rather than failing the whole build (e.g. sklearn is not a hard dep).
        continue
    _ml_datas += _d
    _ml_binaries += _b
    _ml_hiddenimports += _h

a = Analysis(
    ["main.py"],
    pathex=[str(Path(".").resolve())],
    binaries=_ml_binaries,
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
