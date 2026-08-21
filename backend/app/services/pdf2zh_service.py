"""pdf2zh-next (PDFMathTranslate-next) whole-PDF translation engine.

pdf2zh-next is the fast, layout-preserving successor of BabelDOC and also
supports the SiliconFlow Free service used by the popular GUI.  It lives in
an isolated virtual environment so its Gradio/scipy/onnx dependencies never
conflict with ResearchMate's own runtime.  The backend talks to it through
``backend/scripts/pdf2zh_bridge.py`` and falls back to BabelDOC when it is
not installed or fails.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable

ProgressCallback = Callable[[float, str], None]

_PLACEHOLDER_KEYS = {"sk-xxx", "sk-placeholder", "sk-[YOUR_API_KEY]", "sk-sandbox-placeholder"}


def _project_backend() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _bridge_path() -> str | None:
    env = os.environ.get("PDF2ZH_BRIDGE", "").strip()
    if env and os.path.isfile(env):
        return env
    candidates = [
        os.path.join(_project_backend(), "scripts", "pdf2zh_bridge.py"),
        os.path.join(os.path.dirname(sys.executable), "pdf2zh_bridge.py"),
        os.path.join(os.path.dirname(sys.executable), "scripts", "pdf2zh_bridge.py"),
    ]
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, os.path.join(str(sys._MEIPASS), "scripts", "pdf2zh_bridge.py"))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def _python_path() -> str | None:
    env = os.environ.get("PDF2ZH_PYTHON", "").strip()
    if env and os.path.isfile(env):
        return env
    if importlib.util.find_spec("pdf2zh_next") is not None:
        return sys.executable

    candidates = [
        os.path.join(_project_backend(), ".venv-pdf2zh", "Scripts", "python.exe"),
        os.path.join(_project_backend(), "tools", "pdf2zh", "Scripts", "python.exe"),
    ]
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.extend(
            [
                os.path.join(exe_dir, "pdf2zh", "Scripts", "python.exe"),
                os.path.join(exe_dir, "resources", "pdf2zh", "Scripts", "python.exe"),
            ]
        )
    else:
        candidates.append(os.path.join(_project_backend(), ".venv-pdf2zh", "Scripts", "pythonw.exe"))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def is_available() -> bool:
    return bool(_python_path() and _bridge_path())


def install_hint() -> str:
    return (
        "未检测到 pdf2zh-next 隔离环境。请先执行：\n"
        'backend\\.venv-pdf2zh\\Scripts\\python -m pip install "pdf2zh-next==2.9.0"\n'
        "或在 .env 中配置 PDF2ZH_PYTHON 指向 pdf2zh-next 的 python.exe。"
    )


def _is_placeholder_key(key: str) -> bool:
    key = (key or "").strip()
    return not key or key in _PLACEHOLDER_KEYS


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _engine_config(llm_cfg: dict[str, Any], requested: str | None = None) -> dict[str, Any]:
    """Choose the fastest usable pdf2zh-next engine without changing app logic."""
    requested = (requested or os.environ.get("PDF2ZH_ENGINE") or "auto").strip().lower()
    api_key = (llm_cfg.get("api_key") or "").strip()
    base_url = (llm_cfg.get("base_url") or "").strip()
    model = (llm_cfg.get("model") or "gpt-4o-mini").strip()
    sf_key = (os.environ.get("PDF2ZH_SILICONFLOW_API_KEY", "") or "").strip()

    if requested in ("siliconflowfree", "free"):
        return {"engine": "siliconflowfree"}
    if requested == "siliconflow":
        key = sf_key or api_key
        if _is_placeholder_key(key):
            raise ValueError("SiliconFlow 翻译需要 API Key（PDF2ZH_SILICONFLOW_API_KEY）")
        return {
            "engine": "siliconflow",
            "base_url": os.environ.get("PDF2ZH_SILICONFLOW_BASE_URL") or "https://api.siliconflow.cn/v1",
            "api_key": key,
            "model": os.environ.get("PDF2ZH_SILICONFLOW_MODEL") or "deepseek-ai/DeepSeek-V3",
        }
    if requested == "openai":
        if _is_placeholder_key(api_key):
            raise ValueError("OpenAI 整篇翻译需要有效的 LLM API Key")
        return {"engine": "openai", "base_url": base_url, "api_key": api_key, "model": model}
    if requested == "deepl":
        key = api_key or os.environ.get("DEEPL_API_KEY", "")
        if _is_placeholder_key(key):
            raise ValueError("DeepL 整篇翻译需要 DeepL API Key")
        return {"engine": "deepl", "api_key": key}

    # auto: use configured SiliconFlow key, then the user's LLM, then the free service.
    if sf_key and not _is_placeholder_key(sf_key):
        return {
            "engine": "siliconflow",
            "base_url": os.environ.get("PDF2ZH_SILICONFLOW_BASE_URL") or "https://api.siliconflow.cn/v1",
            "api_key": sf_key,
            "model": os.environ.get("PDF2ZH_SILICONFLOW_MODEL") or "deepseek-ai/DeepSeek-V3",
        }
    if not _is_placeholder_key(api_key):
        return {"engine": "openai", "base_url": base_url, "api_key": api_key, "model": model}
    return {"engine": "siliconflowfree"}


def write_glossary_csv(user_id: str, output_dir: str, lang_out: str) -> str | None:
    """Export the user's saved glossary into BabelDOC-compatible CSV for pdf2zh."""
    from app.services import glossary_service

    terms = glossary_service.list_terms(str(user_id))
    rows = []
    for term in terms:
        source = (term.get("term") or "").strip()
        target = (term.get("translation") or "").strip()
        tgt = (term.get("target_lang") or "").strip().lower()
        if not source or not target:
            continue
        if tgt and tgt != "auto" and tgt != lang_out.lower():
            continue
        rows.append((source, target))
    if not rows:
        return None

    path = os.path.join(output_dir, "pdf2zh_glossary.csv")
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target"])
        writer.writerows(rows)
    return path


def _run_bridge(
    python: str,
    bridge: str,
    cfg_path: str,
    timeout: int,
    progress_cb: ProgressCallback | None,
) -> list[str]:
    cmd = [python, bridge, cfg_path]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
        env=env,
    )
    q: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stderr_lines: list[str] = []
    stderr_lock = threading.Lock()

    def pump(pipe, kind: str):
        for line in iter(pipe.readline, ""):
            q.put((kind, line))
        q.put((kind, None))

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True),
    ]
    for t in threads:
        t.start()

    deadline = time.monotonic() + max(60, int(timeout))
    pending = 2
    result: dict[str, Any] | None = None
    try:
        while pending > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"pdf2zh-next 翻译超时（>{timeout}s），已终止")
            try:
                kind, line = q.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if line is None:
                pending -= 1
                continue
            if kind == "err":
                with stderr_lock:
                    stderr_lines.append(line)
                continue
            line = line.strip()
            if line.startswith("EVENT "):
                try:
                    event = json.loads(line[6:])
                except (ValueError, TypeError):
                    continue
                if event.get("type") in ("progress_start", "progress_update", "progress_end"):
                    overall = float(event.get("overall_progress") or 0)
                    stage = str(event.get("stage") or "")
                    if progress_cb:
                        progress_cb(overall, stage)
            elif line.startswith("RESULT "):
                try:
                    result = json.loads(line[7:])
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(f"pdf2zh-next 返回了无法解析的结果：{exc}") from exc
                if not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or "pdf2zh-next 翻译失败"))
                files = [
                    f
                    for f in (result.get("files") or [])
                    if os.path.isfile(f) and f.lower().endswith(".pdf")
                ]
                if not files:
                    raise RuntimeError("pdf2zh-next 未生成翻译 PDF")
                return files
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for t in threads:
            t.join(timeout=1)

    tail = "".join(stderr_lines[-80:])[-1600:]
    raise RuntimeError(f"pdf2zh-next 未返回结果。\n{tail or '（无 stderr）'}")


def translate_pdf(
    pdf_path: str,
    output_dir: str,
    lang_in: str,
    lang_out: str,
    llm_cfg: dict[str, Any],
    qps: int = 4,
    timeout: int | None = None,
    progress_cb: ProgressCallback | None = None,
    engine: str | None = None,
) -> list[str]:
    """Translate a PDF with pdf2zh-next and return generated PDF paths."""
    python = _python_path()
    bridge = _bridge_path()
    if not python or not bridge:
        raise RuntimeError(install_hint())

    engine_cfg = _engine_config(llm_cfg, engine)
    timeout = int(timeout or os.environ.get("PDF2ZH_TIMEOUT") or 3600)
    os.makedirs(output_dir, exist_ok=True)
    cfg = {
        **engine_cfg,
        "input": os.path.abspath(pdf_path),
        "output": os.path.abspath(output_dir),
        "lang_in": lang_in,
        "lang_out": lang_out,
        "qps": max(1, min(int(qps or 4), 20)),
        "report_interval": float(os.environ.get("PDF2ZH_REPORT_INTERVAL") or 0.2),
        "no_mono": True,
        "watermark": os.environ.get("PDF2ZH_WATERMARK") or "no_watermark",
        "translate_table": _env_bool("PDF2ZH_TRANSLATE_TABLE", False),
        "auto_glossary": _env_bool("PDF2ZH_AUTO_GLOSSARY", False),
        "skip_scanned_detection": _env_bool("PDF2ZH_SKIP_SCANNED", False),
    }
    cfg_path = os.path.join(output_dir, ".pdf2zh_request.json")
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
        return _run_bridge(python, bridge, cfg_path, timeout, progress_cb)
    finally:
        try:
            os.remove(cfg_path)
        except OSError:
            pass


def pick_translated_pdf(files: list[str]) -> str | None:
    """Prefer the bilingual/dual PDF, otherwise return the first PDF."""
    if not files:
        return None
    for f in files:
        low = os.path.basename(f).lower()
        if "dual" in low or "bilingual" in low:
            return f
    return files[0]
