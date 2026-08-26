import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_bulk_delete_removes_related_records_and_pdf(client: TestClient) -> None:
    token = client.post("/api/v1/auth/auto").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    from app.config import settings
    from app.database import SessionLocal
    from app.models.annotation import Annotation
    from app.models.paper import Paper
    from app.models.paper_chunk import PaperChunk
    from app.models.paper_chat import PaperChatMessage
    from app.models.user import User

    os.makedirs(settings.PDF_DIR, exist_ok=True)
    filename = "bulk-delete-test.pdf"
    filepath = os.path.join(settings.PDF_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(b"%PDF-1.4\n")

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "researcher").first()
        paper = Paper(
            user_id=user.id,
            title="bulk delete target",
            source="bulk-delete-test",
            status="ready",
            file_path=f"/pdfs/{filename}",
        )
        db.add(paper)
        db.flush()
        db.add(
            PaperChunk(
                paper_id=paper.id,
                dimension="method",
                content="method evidence",
            )
        )
        db.add(
            Annotation(
                user_id=user.id,
                paper_id=paper.id,
                type="highlight",
            )
        )
        db.add(
            PaperChatMessage(
                user_id=user.id,
                paper_id=paper.id,
                role="user",
                content="What is this paper about?",
            )
        )
        kept = Paper(
            user_id=user.id,
            title="bulk delete keeper",
            source="bulk-delete-test",
            status="ready",
        )
        db.add(kept)
        db.commit()
        paper_id = str(paper.id)
        kept_id = str(kept.id)

    resp = client.post(
        "/api/v1/papers/bulk-delete",
        headers=headers,
        json={"ids": [paper_id, "missing-id"]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1}
    assert not os.path.exists(filepath)

    with SessionLocal() as db:
        assert db.query(Paper).filter(Paper.source == "bulk-delete-test").count() == 1
        assert db.query(PaperChunk).filter(PaperChunk.paper_id == paper_id).count() == 0
        assert db.query(Annotation).filter(Annotation.paper_id == paper_id).count() == 0
        assert db.query(PaperChatMessage).filter(PaperChatMessage.paper_id == paper_id).count() == 0
        db.query(Paper).filter(Paper.id == kept_id).delete()
        db.commit()
