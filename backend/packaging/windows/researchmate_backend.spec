# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把后端 FastAPI 应用打包为单个 exe，并内嵌前端 dist。

在 packaging/windows 目录下运行：
    pyinstaller researchmate_backend.spec
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# 打包目录（pyinstaller 需在 packaging/windows 目录下运行）
PACK = os.path.abspath(os.getcwd())
BACKEND_DIR = os.path.abspath(os.path.join(PACK, "..", ".."))          # /project/backend
PROJECT_ROOT = os.path.abspath(os.path.join(PACK, "..", "..", ".."))   # /project
FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")

# 内嵌前端构建产物（解包后位于 <bundle>/dist，main.py 会自动识别）
datas = [(FRONTEND_DIST, "dist")] if os.path.isdir(FRONTEND_DIST) else []

binaries = []
hiddenimports = collect_submodules("app") + [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.postgresql",
    "psycopg2",
]

# 收集带数据文件/动态导入的第三方库
        for pkg in ("litellm", "openai", "tiktoken", "tiktoken_ext", "pydantic", "pymupdf"):
            try:
                d, b, h = collect_all(pkg)
                datas += d
                binaries += b
                hiddenimports += h
            except Exception:
                pass

a = Analysis(
    [os.path.join(BACKEND_DIR, "run.py")],
    pathex=[BACKEND_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ResearchMate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,      # 无控制台窗口（后台运行）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)