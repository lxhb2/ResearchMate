"""Core FastAPI routes against an isolated temporary SQLite database."""
import io
import json
import os
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_root_and_docs_available(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["app"] == "ResearchMate"
    assert client.get("/docs").status_code == 200


def test_auto_login(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/auto")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["username"] == "researcher"


def test_settings_requires_auth_and_returns_defaults(client: TestClient) -> None:
    assert client.get("/api/v1/settings").status_code == 401
    token = client.post("/api/v1/auth/auto").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/settings", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme_color"] == "#4f46e5"
    assert body["llm_api_key"] == ""


def test_list_papers_uses_pagination(client: TestClient) -> None:
    token = client.post("/api/v1/auth/auto").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    from app.database import SessionLocal
    from app.models.paper import Paper
    from app.models.user import User

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "researcher").first()
        for i in range(3):
            db.add(
                Paper(
                    user_id=user.id,
                    title=f"pagination test paper {i}",
                    source="pagination-test",
                    status="ready",
                )
            )
        db.commit()
    try:
        resp = client.get(
            "/api/v1/papers",
            headers=headers,
            params={"page": 2, "limit": 1, "search": "pagination test paper"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["page"] == 2
        assert len(body["items"]) == 1
    finally:
        with SessionLocal() as db:
            db.query(Paper).filter(Paper.source == "pagination-test").delete()
            db.commit()


def test_backup_includes_agent_data(client: TestClient) -> None:
    token = client.post("/api/v1/auth/auto").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    agent_root = os.path.join(os.environ["STORAGE_DIR"], "agent", "plugins", "demo")
    os.makedirs(agent_root, exist_ok=True)
    with open(os.path.join(agent_root, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "demo", "version": "1.0.0"}, f)

    resp = client.get("/api/v1/backup/export", headers=headers)
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert any(name.startswith("agent/") for name in names)


def test_agent_tools_endpoint_lists_builtin_and_mcp(client: TestClient) -> None:
    token = client.post("/api/v1/auth/auto").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/api/v1/agent/capabilities", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    names = [t["name"] for t in body["builtin"]]
    assert "workflow_execute" in names
    assert "mcp" in body


def test_fulltext_and_tasks_endpoints(client: TestClient) -> None:
    token = client.post("/api/v1/auth/auto").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    from app.database import SessionLocal
    from app.models.paper import Paper
    from app.models.user import User
    from app.services import task_queue

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "researcher").first()
        paper = Paper(
            user_id=user.id,
            title="Fulltext Endpoint Paper",
            full_text="A transformer model for quantum chemistry endpoint search.",
            status="ready",
            analysis_status="done",
        )
        db.add(paper)
        db.commit()
        db.refresh(paper)
        task_queue.enqueue(db, user.id, "paper_processing", {"paper_id": str(paper.id)})

    resp = client.post(
        "/api/v1/search/fulltext",
        headers=headers,
        json={"query": "transformer quantum"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    tasks = client.get("/api/v1/tasks", headers=headers).json()["items"]
    assert any(t["task_type"] == "paper_processing" for t in tasks)
