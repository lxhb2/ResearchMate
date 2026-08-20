"""后台任务状态接口：进度页与失败重试。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agent_task import AgentTask
from app.models.user import User

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_out(t: AgentTask) -> dict:
    return {
        "id": str(t.id),
        "task_type": t.task_type,
        "payload": t.payload or {},
        "status": t.status,
        "attempts": t.attempts,
        "max_attempts": t.max_attempts,
        "error": t.error,
        "result": t.result or {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("")
def list_tasks(
    status: str = "",
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前用户的后台任务（可按状态过滤）。"""
    q = db.query(AgentTask).filter(AgentTask.user_id == user.id)
    if status:
        q = q.filter(AgentTask.status == status)
    rows = q.order_by(AgentTask.created_at.desc()).limit(min(max(limit, 1), 200)).all()
    return {"count": len(rows), "items": [_task_out(t) for t in rows]}


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(AgentTask, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_out(task)


@router.post("/{task_id}/retry")
def retry_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """把失败/成功的任务重新放回队列执行。"""
    task = db.get(AgentTask, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "pending"
    task.attempts = 0
    task.error = None
    db.commit()
    return _task_out(task)
