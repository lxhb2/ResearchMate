"""BabelDOC 整篇 PDF 翻译引擎接入（可选外部依赖）。

BabelDOC 是 PDF 级翻译工具：解析版式、批量调用 LLM、保持排版并输出
双语/单语 PDF，适合替代逐段 LLM 翻译的慢速链路。
本服务通过 CLI 调用，未安装时自动降级为现有翻译流程。
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _cli_path() -> str | None:
    """返回 babeldoc CLI 路径（优先当前 Python 环境）。"""
    exe = shutil.which("babeldoc")
    if exe:
        return exe
    if sys.executable:
        scripts = os.path.dirname(sys.executable)
        for name in ("babeldoc.exe", "babeldoc"):
            cand = os.path.join(scripts, name)
            if os.path.isfile(cand):
                return cand
    return None


def is_available() -> bool:
    """BabelDOC 是否已安装。"""
    return importlib.util.find_spec("babeldoc") is not None or _cli_path() is not None


def install_hint() -> str:
    return "当前环境未安装 BabelDOC。请执行：pip install BabelDOC"


def translate_pdf(
    pdf_path: str,
    output_dir: str,
    lang_in: str,
    lang_out: str,
    llm_cfg: dict[str, Any],
    qps: int = 4,
    timeout: int = 1800,
) -> list[str]:
    """调用 BabelDOC CLI 翻译 PDF，返回输出目录中的 PDF 文件列表。"""
    cli = _cli_path()
    if not cli:
        raise RuntimeError(install_hint())
    api_key = (llm_cfg.get("api_key") or "").strip()
    base_url = (llm_cfg.get("base_url") or "").strip()
    model = (llm_cfg.get("model") or "gpt-4o-mini").strip()
    if not api_key or api_key in ("sk-xxx", "sk-placeholder", "sk-[YOUR_API_KEY]"):
        raise ValueError("未配置可用的 LLM API Key，无法调用 BabelDOC 翻译")

    cmd = [
        cli,
        "--openai",
        "--openai-model", model,
        "--openai-base-url", base_url,
        "--openai-api-key", api_key,
        "--files", os.path.abspath(pdf_path),
        "--output", os.path.abspath(output_dir),
        "--lang-in", lang_in,
        "--lang-out", lang_out,
        "--qps", str(max(1, min(qps, 20))),
    ]
    os.makedirs(output_dir, exist_ok=True)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1200:]
        raise RuntimeError(f"BabelDOC 翻译失败（exit {proc.returncode}）：\n{tail}")

    # CLI 会输出双语/单语等多份 PDF，全部返回给调用方挑选
    out = []
    input_name = os.path.basename(os.path.abspath(pdf_path)).lower()
    for f in sorted(Path(output_dir).glob("*.pdf")):
        if f.name.lower() != input_name:
            out.append(str(f))
    return out


def pick_translated_pdf(files: list[str]) -> str | None:
    """优先返回双语翻译件，其次第一份。"""
    if not files:
        return None
    for f in files:
        low = os.path.basename(f).lower()
        if "dual" in low or "bilingual" in low:
            return f
    return files[0]
