"""P0-P1 功能回归测试：全文检索、DOI 用户级唯一、密钥、沙箱、导出、任务队列。"""
import uuid

from app.database import SessionLocal
from app.models.annotation import Annotation
from app.models.paper import Paper
from app.models.user import User
from app.services import annotation_export, fts_service, sandbox_service, settings_service, task_queue
from app.utils import secrets as secret_utils
from app.utils.security import hash_password


def _user(username: str) -> User:
    with SessionLocal() as db:
        u = User(username=username, password=hash_password("testpass123"))
        db.add(u)
        db.commit()
        db.refresh(u)
        return u


def _paper(user_id, title="FTS Test Paper", doi=None, full_text="") -> Paper:
    with SessionLocal() as db:
        p = Paper(
            user_id=user_id,
            title=title,
            doi=doi,
            status="ready",
            full_text=full_text or title,
            analysis_status="done",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return p


def test_doi_unique_per_user() -> None:
    u1 = _user(f"doi-a-{uuid.uuid4().hex[:8]}")
    u2 = _user(f"doi-b-{uuid.uuid4().hex[:8]}")
    _paper(u1.id, doi="10.1000/per-user-test")
    _paper(u2.id, doi="10.1000/per-user-test")
    with SessionLocal() as db:
        count = db.query(Paper).filter(Paper.doi == "10.1000/per-user-test").count()
    assert count == 2


def test_fts5_fulltext_search() -> None:
    user = _user(f"fts-{uuid.uuid4().hex[:8]}")
    p = _paper(
        user.id,
        title="Quantum Transformer Survey",
        full_text="This survey reviews transformer architectures for quantum chemistry simulation.",
    )
    fts_service.ensure_fts()
    with SessionLocal() as db:
        result = fts_service.fts_search(db, "transformer quantum", user_id=user.id)
    assert result["total"] >= 1
    assert any(item["paper_id"] == str(p.id) for item in result["items"])


def test_secret_encryption_roundtrip() -> None:
    raw = "sk-test-secret-123456"
    encrypted = secret_utils.encrypt_secret(raw)
    assert encrypted.startswith("enc:")
    assert secret_utils.decrypt_secret(encrypted) == raw

    user = _user(f"secret-{uuid.uuid4().hex[:8]}")
    with SessionLocal() as db:
        settings_service.update_many(db, user.id, {"llm_api_key": raw})
        cfg = settings_service.get_llm_config(db, user.id)
    assert cfg["api_key"] == raw


def test_sandbox_filters_env_and_runs() -> None:
    result = sandbox_service.run_python(
        "import os\nprint('LLM_API_KEY' in os.environ)\nprint(1 + 1)",
        timeout=10,
    )
    assert "False" in result.output
    assert "2" in result.output


def test_annotation_export_formats() -> None:
    user = _user(f"export-{uuid.uuid4().hex[:8]}")
    p = _paper(user.id, title="Export Me")
    with SessionLocal() as db:
        db.add(
            Annotation(
                user_id=user.id,
                paper_id=p.id,
                type="note",
                content="原文片段",
                comment="这是我的研究笔记",
                page_number=3,
                tags=["重要"],
            )
        )
        db.commit()
        md, fn, _mt = annotation_export.export_annotations(db, user.id, fmt="md")
        js, _fn2, _mt2 = annotation_export.export_annotations(db, user.id, fmt="json")
        rdf, _fn3, _mt3 = annotation_export.export_annotations(db, user.id, fmt="rdf")
    assert "这是我的研究笔记" in md
    assert "这是我的研究笔记" in js
    assert "<z:itemType>note</z:itemType>" in rdf


def test_task_queue_enqueue_and_dispatch() -> None:
    user = _user(f"task-{uuid.uuid4().hex[:8]}")
    with SessionLocal() as db:
        task = task_queue.enqueue(db, user.id, "paper_processing", {"paper_id": "missing-paper"})
        result = task_queue._dispatch(task)
    assert result["ok"] is True
