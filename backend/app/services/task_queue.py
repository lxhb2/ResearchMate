"""SQLite 持久化任务队列：替代内存 BackgroundTasks，支持重启恢复与重试。"""
import threading
import time
import os
import shutil
import tempfile
from typing import Optional

from app.database import SessionLocal
from app.models.agent_task import AgentTask


_last_progress_ts = 0.0


def enqueue(db, user_id, task_type: str, payload: dict, max_attempts: int = 3) -> AgentTask:
    """向队列写入一个待执行任务。"""
    task = AgentTask(
        user_id=str(user_id),
        task_type=task_type,
        payload=payload or {},
        status="pending",
        max_attempts=max_attempts,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _claim_next() -> Optional[AgentTask]:
    """原子领取一个 pending 任务并标记 running（SQLite 单写场景足够）。"""
    with SessionLocal() as db:
        task = (
            db.query(AgentTask)
            .filter(AgentTask.status == "pending")
            .order_by(AgentTask.created_at.asc())
            .first()
        )
        if task is None:
            return None
        task.status = "running"
        task.attempts = (task.attempts or 0) + 1
        db.commit()
        db.refresh(task)
        # 分离对象，避免会话关闭后懒加载
        payload = dict(task.payload or {})
        return AgentTask(
            id=task.id,
            user_id=task.user_id,
            task_type=task.task_type,
            payload=payload,
            status="running",
            attempts=task.attempts,
            max_attempts=task.max_attempts,
        )


def _finish(task_id, error: Optional[str] = None, result: Optional[dict] = None) -> None:
    with SessionLocal() as db:
        task = db.get(AgentTask, str(task_id))
        if task is None:
            return
        if error:
            task.error = str(error)[:2000]
            if (task.attempts or 0) >= (task.max_attempts or 3):
                task.status = "failed"
            else:
                task.status = "pending"
        else:
            task.status = "success"
            task.result = result or {}
        db.commit()


def _update_task_progress(task_id: str, progress: float, stage: str) -> None:
    """Persist a throttled progress snapshot into the task result JSON."""
    global _last_progress_ts

    now = time.time()
    if now - _last_progress_ts < 1.0 and progress < 99:
        return
    _last_progress_ts = now
    with SessionLocal() as db:
        task = db.get(AgentTask, str(task_id))
        if task is None:
            return
        result = dict(task.result or {})
        result["progress"] = round(max(0.0, min(float(progress), 100.0)), 1)
        result["stage"] = stage
        task.result = result
        db.commit()


def _dispatch(task: AgentTask) -> dict:
    """按任务类型分发执行。"""
    if task.task_type == "paper_processing":
        from app.routers.papers import _run_processing

        paper_id = str((task.payload or {}).get("paper_id") or "")
        if not paper_id:
            raise ValueError("paper_processing 任务缺少 paper_id")
        _run_processing(paper_id)
        return {"ok": True, "paper_id": paper_id}
    if task.task_type == "conversation_summary":
        return _summarize_conversation(task)
    if task.task_type == "babeldoc_translate":
        return _run_babeldoc_translate(task)
    raise ValueError(f"未知任务类型：{task.task_type}")


def _run_babeldoc_translate(task: AgentTask) -> dict:
    """后台执行整篇 PDF 翻译（优先 pdf2zh-next，失败回退 BabelDOC）。"""
    from app.config import settings
    from app.models.paper import Paper
    from app.services import babeldoc_service, pdf2zh_service, settings_service

    paper_id = str((task.payload or {}).get("paper_id") or "")
    lang_in = str((task.payload or {}).get("lang_in") or "en")
    lang_out = str((task.payload or {}).get("lang_out") or "zh")
    engine = str((task.payload or {}).get("engine") or "auto")
    page_range = str((task.payload or {}).get("page_range") or "").strip()
    if not paper_id:
        raise ValueError("babeldoc_translate 任务缺少 paper_id")

    with SessionLocal() as db:
        paper = db.get(Paper, paper_id)
        if paper is None:
            raise ValueError("论文不存在")
        src = os.path.join(settings.PDF_DIR, os.path.basename(paper.file_path or ""))
        if not os.path.isfile(src):
            raise ValueError("PDF 文件不存在")
        cfg = settings_service.get_llm_config(db, str(task.user_id))

    # PDF hash cache: skip re-translation for the same file + language + page range
    cache_dir = os.path.join(settings.STORAGE_DIR, "translation_cache")
    try:
        cache_key = pdf2zh_service.pdf_cache_key(src, lang_in, lang_out, page_range or None)
        cached_path = pdf2zh_service.find_cached_pdf(cache_dir, cache_key)
        if cached_path:
            out_root = os.path.join(settings.STORAGE_DIR, "translations", str(task.id))
            os.makedirs(out_root, exist_ok=True)
            final_path = os.path.join(out_root, f"{paper.title or 'paper'}-{lang_out}.pdf")
            shutil.copy2(cached_path, final_path)
            _update_task_progress(str(task.id), 100.0, "缓存命中，直接返回上次翻译结果")
            return {
                "ok": True,
                "output_path": final_path,
                "paper_title": paper.title,
                "engine": "cache",
                "progress": 100,
                "stage": "缓存命中",
            }
    except Exception:
        pass

    out_root = os.path.join(settings.STORAGE_DIR, "translations", str(task.id))
    os.makedirs(out_root, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="babeldoc_task_")
    try:
        input_pdf = os.path.join(tmpdir, "input.pdf")
        shutil.copy2(src, input_pdf)
        pdf_error = ""
        files: list[str] = []
        chosen: str | None = None
        engine_used = "babeldoc"

        if pdf2zh_service.is_available():
            _update_task_progress(str(task.id), 1, "启动 pdf2zh-next 快速翻译引擎")
            glossary_path = pdf2zh_service.write_glossary_csv(
                str(task.user_id), tmpdir, lang_out
            )
            attempts = [engine]
            if engine not in ("siliconflowfree", "free"):
                attempts.append("siliconflowfree")
            for attempt_engine in attempts:
                try:
                    files = pdf2zh_service.translate_pdf(
                        input_pdf,
                        os.path.join(tmpdir, "out"),
                        lang_in,
                        lang_out,
                        cfg,
                        engine=attempt_engine,
                        pages=page_range or None,
                        progress_cb=lambda p, stage: _update_task_progress(str(task.id), p, stage),
                    )
                    chosen = pdf2zh_service.pick_translated_pdf(files)
                    engine_used = "pdf2zh-next"
                    if glossary_path:
                        os.remove(glossary_path)
                    break
                except Exception as e:  # noqa: BLE001
                    pdf_error = (pdf_error + " | " if pdf_error else "") + f"{attempt_engine}: {e}"
                    _update_task_progress(
                        str(task.id),
                        0,
                        f"pdf2zh-next（{attempt_engine}）失败，尝试备用引擎",
                    )

        if not chosen and babeldoc_service.is_available():
            try:
                files = babeldoc_service.translate_pdf(
                    input_pdf,
                    os.path.join(tmpdir, "out"),
                    lang_in,
                    lang_out,
                    cfg,
                )
                chosen = babeldoc_service.pick_translated_pdf(files)
                engine_used = "babeldoc"
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(
                    f"整篇翻译失败。pdf2zh-next：{pdf_error or '未安装'}；BabelDOC：{e}"
                ) from e

        if not chosen or not os.path.isfile(chosen):
            raise ValueError(
                f"翻译引擎未生成 PDF。pdf2zh-next：{pdf_error or '未使用'}；"
                "BabelDOC：未使用或不可用"
            )
        final_path = os.path.join(out_root, f"{paper.title or 'paper'}-{lang_out}.pdf")
        shutil.copy2(chosen, final_path)
        try:
            save_key = pdf2zh_service.pdf_cache_key(input_pdf, lang_in, lang_out, page_range or None)
            pdf2zh_service.save_to_cache(cache_dir, save_key, chosen)
        except Exception:
            pass
        return {
            "ok": True,
            "output_path": final_path,
            "paper_title": paper.title,
            "engine": engine_used,
            "progress": 100,
            "stage": "翻译完成",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _summarize_conversation(task: AgentTask) -> dict:
    """把长对话压缩成摘要，追加到长期记忆 conversations.md。"""
    from app.agent import memory as memory_mod
    from app.agent.llm_adapter import LLMAdapter
    from app.services import settings_service

    messages = (task.payload or {}).get("messages") or []
    if not messages:
        return {"ok": True, "skipped": True, "reason": "no messages"}
    with SessionLocal() as db:
        cfg = settings_service.get_llm_config(db, str(task.user_id))
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key or api_key in ("sk-xxx", "sk-placeholder", "sk-[YOUR_API_KEY]"):
        return {"ok": True, "skipped": True, "reason": "no llm key"}
    llm = LLMAdapter.from_config(cfg)
    if llm.provider == "mock":
        return {"ok": True, "skipped": True, "reason": "mock llm"}
    lines = []
    for m in messages[-12:]:
        role = "用户" if m.get("role") == "user" else "助手"
        content = str(m.get("content") or "")[:1200]
        if content:
            lines.append(f"{role}：{content}")
    if not lines:
        return {"ok": True, "skipped": True, "reason": "empty summary input"}
    prompt = "以下是用户与科研助手的对话，请压缩成 3-5 句中文摘要，记录主题、结论与待办。只输出摘要。\n\n" + "\n\n".join(lines)
    summary = llm.chat(
        [
            {"role": "system", "content": "你是科研助手记忆管家，负责把长对话压缩成可长期使用的会话摘要。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=400,
    ).strip()
    if not summary:
        return {"ok": True, "skipped": True, "reason": "empty summary"}
    memory_mod.write_memory(str(task.user_id), "conversations.md", summary, append=True)
    return {"ok": True, "summary": summary[:200]}


def _worker_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        task = _claim_next()
        if task is None:
            stop_event.wait(0.5)
            continue
        try:
            result = _dispatch(task)
            _finish(task.id, result=result)
        except Exception as e:  # noqa: BLE001
            _finish(task.id, error=str(e))


_worker_started = False
_worker_stop: threading.Event | None = None


def start_worker() -> None:
    """启动后台 worker（幂等，daemon 线程）。"""
    global _worker_started, _worker_stop
    if _worker_started:
        return
    _worker_started = True
    _worker_stop = threading.Event()
    threading.Thread(target=_worker_loop, args=(_worker_stop,), daemon=True).start()


def stop_worker() -> None:
    """测试/退出时停止 worker。"""
    global _worker_stop
    if _worker_stop is not None:
        _worker_stop.set()
