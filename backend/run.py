"""PyInstaller 打包入口：以编程方式启动 FastAPI 应用（单端口，托管前端）。

被 PyInstaller 用作脚本入口，生成无需 Python 环境的 researchmate.exe。
"""
import os
import sys

# 保证在打包后仍能定位 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# PyInstaller 单文件模式：内嵌的前端 dist 位于 <_MEIPASS>/dist。
# 在 import app.main（触发 config 读取环境变量）之前设置 FRONTEND_DIST，
# 使打包产物无需额外配置即可托管前端（单端口）。
if getattr(sys, "frozen", False):
    _meipass = getattr(sys, "_MEIPASS", "")
    if _meipass:
        _embedded_dist = os.path.join(_meipass, "dist")
        if os.path.isdir(_embedded_dist):
            os.environ.setdefault("FRONTEND_DIST", _embedded_dist)

# 无控制台模式（console=False）下 stdout/stderr 为 None，
# uvicorn 日志格式化器会调用 sys.stderr.isatty() 而崩溃。
# 这里把它们重定向到日志文件，既避免崩溃，也便于排查运行问题。
if sys.stdout is None or sys.stderr is None:
    log_path = os.path.join(os.getcwd(), "researchmate.log")
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream

from app.main import app  # noqa: E402  触发应用构建（含建表）
import uvicorn  # noqa: E402


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
    )