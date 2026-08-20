"""SQLite 持久化任务队列：替代内存 BackgroundTasks，支持重启恢复与重试。"""
import threading
import time
from typing import Optional

from app.database import SessionLocal
from app.models.agent_task import AgentTask


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
    raise ValueError(f"未知任务类型：{task.task_type}")


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
