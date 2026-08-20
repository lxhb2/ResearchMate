"""Bridge process that runs pdf2zh-next inside the isolated pdf2zh venv.

ResearchMate's backend invokes this script with a JSON config file.  The
script translates one PDF via ``do_translate_async_stream`` and reports
machine-readable ``EVENT`` / ``RESULT`` lines on stdout so the parent can
show progress without parsing the upstream CLI's rich console output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)

from pdf2zh_next.config.model import BasicSettings, PDFSettings, SettingsModel, TranslationSettings
from pdf2zh_next.config.translate_engine_model import (
    DeepLSettings,
    OpenAISettings,
    SiliconFlowFreeSettings,
    SiliconFlowSettings,
)
from pdf2zh_next.high_level import do_translate_async_stream


def _emit(event: dict) -> None:
    print("EVENT " + json.dumps(event, ensure_ascii=False), flush=True)


def _emit_result(result: dict) -> None:
    print("RESULT " + json.dumps(result, ensure_ascii=False), flush=True)


def _build_engine(cfg: dict):
    engine = str(cfg.get("engine") or "siliconflowfree").lower()
    if engine == "openai":
        return OpenAISettings(
            openai_model=str(cfg.get("model") or "gpt-4o-mini"),
            openai_base_url=(cfg.get("base_url") or "").strip() or None,
            openai_api_key=str(cfg.get("api_key") or "").strip(),
            openai_timeout=str(cfg.get("timeout") or 120),
        )
    if engine == "siliconflow":
        return SiliconFlowSettings(
            siliconflow_model=str(cfg.get("model") or "deepseek-ai/DeepSeek-V3"),
            siliconflow_base_url=(cfg.get("base_url") or "https://api.siliconflow.cn/v1").strip(),
            siliconflow_api_key=str(cfg.get("api_key") or "").strip(),
        )
    if engine == "deepl":
        return DeepLSettings(deepl_auth_key=str(cfg.get("api_key") or "").strip())
    return SiliconFlowFreeSettings()


def _build_settings(cfg: dict) -> SettingsModel:
    glossaries = cfg.get("glossaries") or []
    if isinstance(glossaries, str):
        glossaries = [glossaries]
    glossaries = [g for g in glossaries if g and Path(g).is_file()]

    engine = _build_engine(cfg)
    settings = SettingsModel(
        report_interval=float(cfg.get("report_interval") or 0.2),
        basic=BasicSettings(input_files=set()),
        translation=TranslationSettings(
            lang_in=str(cfg.get("lang_in") or "en"),
            lang_out=str(cfg.get("lang_out") or "zh"),
            output=str(cfg.get("output") or "."),
            qps=int(cfg.get("qps") or 4),
            glossaries=",".join(glossaries) if glossaries else None,
            no_auto_extract_glossary=not bool(cfg.get("auto_glossary", False)),
            custom_system_prompt=(cfg.get("custom_system_prompt") or None),
        ),
        pdf=PDFSettings(
            no_dual=False,
            no_mono=bool(cfg.get("no_mono", True)),
            watermark_output_mode=str(cfg.get("watermark") or "no_watermark"),
            translate_table_text=bool(cfg.get("translate_table", False)),
            skip_scanned_detection=bool(cfg.get("skip_scanned_detection", False)),
            max_pages_per_part=int(cfg["max_pages_per_part"]) if cfg.get("max_pages_per_part") else None,
        ),
        translate_engine_settings=engine,
    )
    settings.validate_settings()
    return settings


async def translate_one(cfg: dict) -> int:
    pdf_path = Path(cfg["input"])
    if not pdf_path.is_file():
        _emit_result({"ok": False, "error": f"input pdf not found: {pdf_path}"})
        return 1

    settings = _build_settings(cfg)
    try:
        import babeldoc.assets.assets as assets

        assets.warmup()
    except Exception:  # noqa: BLE001 - assets may already exist
        pass

    try:
        async for event in do_translate_async_stream(settings, pdf_path):
            etype = event.get("type")
            if etype in ("stage_summary", "progress_start", "progress_update", "progress_end"):
                _emit(event)
            elif etype == "finish":
                res = event.get("translate_result")
                paths = []
                for attr in (
                    "no_watermark_dual_pdf_path",
                    "dual_pdf_path",
                    "no_watermark_mono_pdf_path",
                    "mono_pdf_path",
                    "auto_extracted_glossary_path",
                ):
                    value = getattr(res, attr, None)
                    if value and Path(value).is_file():
                        paths.append(str(value))
                _emit_result(
                    {
                        "ok": True,
                        "engine": str(settings.translate_engine_settings.translate_engine_type),
                        "files": paths,
                        "total_seconds": getattr(res, "total_seconds", None),
                    }
                )
                return 0
            elif etype == "error":
                _emit_result(
                    {
                        "ok": False,
                        "error": str(event.get("error") or "pdf2zh-next translation failed"),
                        "details": str(event.get("details") or ""),
                    }
                )
                return 1
    except Exception as exc:  # noqa: BLE001
        _emit_result({"ok": False, "error": str(exc)})
        return 1

    _emit_result({"ok": False, "error": "pdf2zh-next exited without a finish event"})
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: pdf2zh_bridge.py <config.json>", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"failed to read config: {exc}", file=sys.stderr)
        return 2
    return asyncio.run(translate_one(cfg))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
