import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Depends, HTTPException
import json
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent_task import AgentTask
from app.models.paper import Paper
from app.models.user import User
from app.services import llm_service, settings_service
from app.agent.llm_adapter import LLMAdapter

router = APIRouter(tags=["translate"])


class PdfTranslateRequest(BaseModel):
    paper_id: str
    lang_in: str = "en"
    lang_out: str = "zh"
    engine: str = "auto"


class BatchTranslateRequest(BaseModel):
    texts: list[str]
    target_lang: str = "zh"


def _build_llm(db: Session, user_id) -> LLMAdapter:
    """从用户设置构造 LLM 适配器，无 key/服务不可用时自动降级为 mock。"""
    try:
        cfg = settings_service.get_llm_config(db, str(user_id))
        return LLMAdapter.from_config(cfg)
    except Exception:  # noqa: BLE001
        return LLMAdapter.mock()


def _fast_llm(db: Session, user_id) -> LLMAdapter:
    """短文本快速翻译模型：根据当前厂商自动选更快的模型。"""
    try:
        cfg = settings_service.get_llm_config(db, str(user_id))
    except Exception:  # noqa: BLE001
        return _build_llm(db, user_id)
    model = (cfg.get("model") or "").strip()
    base = (cfg.get("base_url") or "").lower()
    if "openai" in base and not model.endswith("mini"):
        model = "gpt-4o-mini"
    elif "deepseek" in base:
        model = "deepseek-chat"
    elif "dashscope" in base or "aliyun" in base:
        model = "qwen-turbo"
    elif "bigmodel" in base:
        model = "glm-4-flash"
    elif "moonshot" in base:
        model = "moonshot-v1-8k"
    cfg = {**cfg, "model": model}
    return LLMAdapter.from_config(cfg)


def _translate_with_llm(llm: LLMAdapter, text: str, target_lang: str) -> str:
    system = (
        "You are a professional academic translator. Translate the user's text into the target language. "
        "Preserve technical terms accurately. Return ONLY the translation, no explanations."
    )
    user_msg = f"Target language: {target_lang}\n\nText to translate:\n{text}"
    messages = llm_service.system_user(system, user_msg)
    return llm.chat(messages, temperature=0.2, max_tokens=1200).strip()


def _translate_text(db: Session, user_id, text: str, target_lang: str) -> str:
    """带缓存 / DeepL 直连 / LLM 降级的单条翻译。"""
    from app.services import deepl_service, free_translate_service, translation_cache

    text = (text or "").strip()
    if not text:
        return ""
    # 术语表精确命中：个人已保存术语直接秒回
    try:
        from app.services import glossary_service
        hits = glossary_service.search_terms(str(user_id), text, limit=5)
        for hit in hits:
            if hit.get("term", "").strip().lower() == text.lower() and hit.get("translation"):
                translation_cache.set("auto", target_lang, text, hit["translation"])
                return hit["translation"]
    except Exception:  # noqa: BLE001
        pass
    cached = translation_cache.get("auto", target_lang, text)
    if cached is not None:
        return cached
    if deepl_service.available() and len(text) <= 5000:
        try:
            translated = deepl_service.translate(text, target_lang)
            if translated:
                translation_cache.set("auto", target_lang, text, translated)
                return translated
        except Exception:  # noqa: BLE001
            pass
    if free_translate_service.enabled() and len(text) <= 5000:
        try:
            translated = free_translate_service.translate(text, target_lang)
            if translated:
                translation_cache.set("auto", target_lang, text, translated)
                return translated
        except Exception:  # noqa: BLE001
            pass
    llm = _fast_llm(db, user_id) if len(text) <= 300 else _build_llm(db, user_id)
    translation = _translate_with_llm(llm, text, target_lang)
    if translation:
        translation_cache.set("auto", target_lang, text, translation)
    return translation


@router.post("/translate/polish")
def polish_text(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """学术润色：短文本走快速模型，长文本走主模型，结果缓存。"""
    from app.services import translation_cache

    text = (body.get("text") or "").strip()
    if not text:
        return {"polished": ""}
    cached = translation_cache.get("polish", "zh", text)
    if cached is not None:
        return {"polished": cached}
    llm = _fast_llm(db, user.id) if len(text) <= 800 else _build_llm(db, user.id)
    system = (
        "你是学术论文润色专家。请把下面的段落润色为更地道、学术、精炼的文本。"
        "保留原意、术语与公式/引用标注，不要添加额外注释。只返回润色后的文本。"
    )
    messages = llm_service.system_user(system, text)
    polished = llm.chat(messages, temperature=0.2, max_tokens=1600).strip()
    if polished:
        translation_cache.set("polish", "zh", text, polished)
    return {"polished": polished}


@router.post("/translate")
def translate(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    text = body.get("text", "").strip()
    target_lang = body.get("target_lang", "zh")
    save_term = bool(body.get("save_term", False))
    translation = _translate_text(db, user.id, text, target_lang)
    result: dict = {"translation": translation}
    if save_term and text and len(text) <= 200:
        try:
            from app.services import glossary_service
            item = glossary_service.add_term(
                str(user.id),
                text[:100],
                translation=translation,
                source_lang="auto",
                target_lang=target_lang,
            )
            result["saved_term"] = item
        except Exception:  # noqa: BLE001
            pass
    return result


@router.post("/translate/batch")
def translate_batch(
    body: BatchTranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量翻译：并发调用，用于长段落/多选片段加速。"""
    from app.agent.llm_adapter import LLMAdapter
    from app.services import deepl_service, free_translate_service, translation_cache

    texts = [(t or "").strip() for t in (body.texts or [])]
    texts = [t for t in texts if t][:50]
    cfg = settings_service.get_llm_config(db, str(user.id))
    llm = LLMAdapter.from_config(cfg)

    def work(text: str) -> str:
        try:
            from app.services import glossary_service
            hits = glossary_service.search_terms(str(user.id), text, limit=5)
            for hit in hits:
                if hit.get("term", "").strip().lower() == text.lower() and hit.get("translation"):
                    translation_cache.set("auto", body.target_lang, text, hit["translation"])
                    return hit["translation"]
        except Exception:  # noqa: BLE001
            pass
        cached = translation_cache.get("auto", body.target_lang, text)
        if cached is not None:
            return cached
        if deepl_service.available() and len(text) <= 5000:
            try:
                translated = deepl_service.translate(text, body.target_lang)
                if translated:
                    translation_cache.set("auto", body.target_lang, text, translated)
                    return translated
            except Exception:  # noqa: BLE001
                pass
        if free_translate_service.enabled() and len(text) <= 5000:
            try:
                translated = free_translate_service.translate(text, body.target_lang)
                if translated:
                    translation_cache.set("auto", body.target_lang, text, translated)
                    return translated
            except Exception:  # noqa: BLE001
                pass
        fast_llm = _fast_llm(db, str(user.id)) if len(text) <= 300 else llm
        translated = _translate_with_llm(fast_llm, text, body.target_lang)
        if translated:
            translation_cache.set("auto", body.target_lang, text, translated)
        return translated

    results: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(texts) or 1)) as ex:
        futures = {ex.submit(work, t): i for i, t in enumerate(texts)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:  # noqa: BLE001
                results[idx] = ""
    return {"translations": [results.get(i, "") for i in range(len(texts))]}


@router.post("/translate/pdf")
def start_translate_pdf(
    body: PdfTranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """整篇 PDF 翻译：优先 pdf2zh-next，失败时回退 BabelDOC，后台异步执行。"""
    from app.services import babeldoc_service, pdf2zh_service, task_queue

    paper = db.get(Paper, body.paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.file_path:
        raise HTTPException(status_code=400, detail="该文献没有 PDF 附件")
    src = os.path.join(settings.PDF_DIR, os.path.basename(paper.file_path))
    if not os.path.isfile(src):
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    if not pdf2zh_service.is_available() and not babeldoc_service.is_available():
        raise HTTPException(status_code=501, detail=pdf2zh_service.install_hint())
    task = task_queue.enqueue(
        db,
        user.id,
        "babeldoc_translate",
        {
            "paper_id": body.paper_id,
            "lang_in": body.lang_in,
            "lang_out": body.lang_out,
            "engine": body.engine or "auto",
        },
    )
    return {
        "ok": True,
        "task_id": str(task.id),
        "status": task.status,
        "engine": "pdf2zh-next" if pdf2zh_service.is_available() else "babeldoc",
    }


@router.get("/translate/pdf/status/{task_id}")
def translate_pdf_status(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询 BabelDOC 整篇翻译任务状态。"""
    task = db.get(AgentTask, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    result = task.result or {}
    return {
        "task_id": str(task.id),
        "status": task.status,
        "error": task.error,
        "output_path": result.get("output_path"),
        "paper_title": result.get("paper_title"),
        "progress": result.get("progress", 100 if task.status == "success" else 0),
        "stage": result.get("stage") or ("" if task.status == "pending" else None),
        "engine": result.get("engine"),
    }


@router.get("/translate/pdf/download/{task_id}")
def translate_pdf_download(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """下载已完成的 BabelDOC 翻译 PDF。"""
    task = db.get(AgentTask, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    result = task.result or {}
    path = result.get("output_path") or ""
    if task.status != "success" or not os.path.isfile(path):
        raise HTTPException(status_code=400, detail="翻译尚未完成或文件不存在")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=os.path.basename(path),
    )


@router.post("/translate/stream")
def translate_stream(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """流式翻译：短文本走缓存/DeepL/免费加速，长文本 SSE 逐 token 返回。"""
    text = body.get("text", "").strip()
    target_lang = body.get("target_lang", "zh")
    if not text:
        return {"translation": ""}
    from app.services import deepl_service, free_translate_service, translation_cache

    cached = translation_cache.get("auto", target_lang, text)
    if cached is not None:
        def cached_gen():
            yield f"data: {json.dumps({'delta': cached})}\n\n"

        return StreamingResponse(cached_gen(), media_type="text/event-stream")

    fast_result = ""
    if len(text) <= 5000:
        if deepl_service.available():
            try:
                fast_result = deepl_service.translate(text, target_lang)
            except Exception:  # noqa: BLE001
                fast_result = ""
        if not fast_result and free_translate_service.enabled():
            try:
                fast_result = free_translate_service.translate(text, target_lang)
            except Exception:  # noqa: BLE001
                fast_result = ""
    if fast_result:
        translation_cache.set("auto", target_lang, text, fast_result)

        def fast_gen():
            yield f"data: {json.dumps({'delta': fast_result})}\n\n"

        return StreamingResponse(fast_gen(), media_type="text/event-stream")

    system = (
        "You are a professional academic translator. Translate the user's text into the target language. "
        "Preserve technical terms accurately. Return ONLY the translation, no explanations."
    )
    user_msg = f"Target language: {target_lang}\n\nText to translate:\n{text}"
    messages = llm_service.system_user(system, user_msg)
    llm = _build_llm(db, user.id)

    def gen():
        # chat_stream 在 LLM 不可达时自动降级为离线 mock 流（含降级提示），不抛异常
        parts: list[str] = []
        for tok in llm.chat_stream(messages, temperature=0.2, max_tokens=1200):
            yield f"data: {json.dumps({'delta': tok})}\n\n"
            parts.append(tok)
        translation_cache.set("auto", target_lang, text, "".join(parts))

    return StreamingResponse(gen(), media_type="text/event-stream")
