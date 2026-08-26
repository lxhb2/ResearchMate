# -*- mode: python ; coding: utf-8 -*-
"""ResearchMate 免 Python 打包配置（SQLite 轻量化版）。

在 packaging/windows_sqlite 目录下运行：
    pyinstaller researchmate_sqlite.spec

产物：单文件 ResearchMate.exe（内嵌前端 dist 与科研 Skill 模板），
运行无需任何 Python 环境，双击 start.bat 即可。
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# 打包目录（pyinstaller 需在 packaging/windows_sqlite 目录下运行）
PACK = os.path.abspath(os.getcwd())
BACKEND_DIR = os.path.abspath(os.path.join(PACK, "..", ".."))          # /project/backend
PROJECT_ROOT = os.path.abspath(os.path.join(PACK, "..", "..", ".."))   # /project
FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")
RESEARCH_TEMPLATES = os.path.join(BACKEND_DIR, "research_skills", "templates")
PDF2ZH_BRIDGE = os.path.join(BACKEND_DIR, "scripts", "pdf2zh_bridge.py")

# 内嵌前端构建产物 -> 解包到 <_MEIPASS>/dist（run.py 自动识别）
datas = [(FRONTEND_DIST, "dist")] if os.path.isdir(FRONTEND_DIST) else []

# 内嵌科研 Skill 模板 -> <_MEIPASS>/research_skills/templates
if os.path.isdir(RESEARCH_TEMPLATES):
    datas.append((RESEARCH_TEMPLATES, os.path.join("research_skills", "templates")))

# pdf2zh-next 桥接脚本（隔离翻译环境是可选的，安装包内只带调用器）
if os.path.isfile(PDF2ZH_BRIDGE):
    datas.append((PDF2ZH_BRIDGE, "scripts"))

binaries = []
hiddenimports = (
    collect_submodules("app")
    + collect_submodules("research_skills")
    + [
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
        "sqlalchemy.dialects.sqlite",
        "jose",
        "jose.jwt",
        "jose.backends",
        "passlib",
        "passlib.context",
    ]
)

# 收集带数据文件/动态导入的第三方库
for pkg in ("litellm", "openai", "tiktoken", "tiktoken_ext", "pydantic", "pymupdf", "pydantic_settings", "jose", "passlib"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001
        pass

a = Analysis(
    [os.path.join(BACKEND_DIR, "run.py")],
    pathex=[BACKEND_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "psycopg2", "asyncpg"],
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
    console=False,      # 无控制台窗口（后台运行，日志写入 researchmate.log）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
