import os
import shutil
import tempfile

from fastapi import APIRouter, Depends, HTTPException
import json
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.paper import Paper
from app.models.user import User
from app.services import llm_service, settings_service
from app.agent.llm_adapter import LLMAdapter

router = APIRouter(tags=["translate"])


class PdfTranslateRequest(BaseModel):
    paper_id: str
    lang_in: str = "en"
    lang_out: str = "zh"


def _build_llm(db: Session, user_id) -> LLMAdapter:
    """从用户设置构造 LLM 适配器，无 key/服务不可用时自动降级为 mock。"""
    try:
        cfg = settings_service.get_llm_config(db, str(user_id))
        return LLMAdapter.from_config(cfg)
    except Exception:  # noqa: BLE001
        return LLMAdapter.mock()


@router.post("/translate")
def translate(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    text = body.get("text", "").strip()
    target_lang = body.get("target_lang", "zh")
    save_term = bool(body.get("save_term", False))
    if not text:
        return {"translation": ""}
    system = (
        "You are a professional academic translator. Translate the user's text into the target language. "
        "Preserve technical terms accurately. Return ONLY the translation, no explanations."
    )
    user_msg = f"Target language: {target_lang}\n\nText to translate:\n{text}"
    messages = llm_service.system_user(system, user_msg)
    # 统一走 LLMAdapter：连接失败自动降级为离线 mock（不抛 500）
    llm = _build_llm(db, user.id)
    translation = llm.chat(messages, temperature=0.2, max_tokens=1200)
    result: dict = {"translation": translation.strip()}
    if save_term and text and len(text) <= 200:
        try:
            from app.services import glossary_service
            item = glossary_service.add_term(
                str(user.id),
                text[:100],
                translation=translation.strip(),
                source_lang="auto",
                target_lang=target_lang,
            )
            result["saved_term"] = item
        except Exception:  # noqa: BLE001
            pass
    return result


@router.post("/translate/pdf")
def translate_pdf(
    body: PdfTranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """BabelDOC 整篇 PDF 翻译：保持排版，输出双语 PDF（可选加速引擎）。"""
    from app.services import babeldoc_service

    paper = db.get(Paper, body.paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.file_path:
        raise HTTPException(status_code=400, detail="该文献没有 PDF 附件")
    src = os.path.join(settings.PDF_DIR, os.path.basename(paper.file_path))
    if not os.path.isfile(src):
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    if not babeldoc_service.is_available():
        raise HTTPException(status_code=501, detail=babeldoc_service.install_hint())
    cfg = settings_service.get_llm_config(db, str(user.id))

    tmpdir = tempfile.mkdtemp(prefix="babeldoc_")
    try:
        input_pdf = os.path.join(tmpdir, "input.pdf")
        shutil.copy2(src, input_pdf)
        outdir = os.path.join(tmpdir, "out")
        files = babeldoc_service.translate_pdf(
            input_pdf,
            outdir,
            body.lang_in,
            body.lang_out,
            cfg,
        )
        chosen = babeldoc_service.pick_translated_pdf(files)
        if not chosen or not os.path.isfile(chosen):
            raise HTTPException(status_code=500, detail="BabelDOC 未生成翻译 PDF")
        filename = f"{paper.title or 'paper'}-{body.lang_out}.pdf"
        return FileResponse(
            chosen,
            media_type="application/pdf",
            filename=filename,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"整篇翻译失败：{e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.post("/translate/stream")
def translate_stream(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """流式翻译：SSE 逐 token 返回。"""
    text = body.get("text", "").strip()
    target_lang = body.get("target_lang", "zh")
    if not text:
        return {"translation": ""}
    system = (
        "You are a professional academic translator. Translate the user's text into the target language. "
        "Preserve technical terms accurately. Return ONLY the translation, no explanations."
    )
    user_msg = f"Target language: {target_lang}\n\nText to translate:\n{text}"
    messages = llm_service.system_user(system, user_msg)
    llm = _build_llm(db, user.id)

    def gen():
        # chat_stream 在 LLM 不可达时自动降级为离线 mock 流（含降级提示），不抛异常
        for tok in llm.chat_stream(messages, temperature=0.2, max_tokens=1200):
            yield f"data: {json.dumps({'delta': tok})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
