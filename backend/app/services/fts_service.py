"""SQLite FTS5 全文检索：论文标题/作者/摘要/全文索引与查询。"""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine

FTS_TABLE = "papers_fts"


def _is_sqlite() -> bool:
    return str(engine.url).startswith("sqlite")


def ensure_fts() -> None:
    """建 FTS5 虚拟表、同步触发器，并回填存量数据。"""
    if not _is_sqlite():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5("
                "paper_id UNINDEXED, user_id UNINDEXED, title, authors, abstract, full_text, "
                "tokenize = 'unicode61 remove_diacritics 2')"
            )
        )
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{FTS_TABLE}_insert"))
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{FTS_TABLE}_delete"))
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{FTS_TABLE}_update"))
        conn.execute(
            text(
                f"CREATE TRIGGER trg_{FTS_TABLE}_insert AFTER INSERT ON papers BEGIN "
                f"INSERT INTO {FTS_TABLE}(paper_id,user_id,title,authors,abstract,full_text) "
                "VALUES (new.id,new.user_id,coalesce(new.title,''),coalesce(new.authors,''),"
                "coalesce(new.abstract,''),coalesce(new.full_text,'')); END"
            )
        )
        conn.execute(
            text(
                f"CREATE TRIGGER trg_{FTS_TABLE}_delete AFTER DELETE ON papers BEGIN "
                f"DELETE FROM {FTS_TABLE} WHERE paper_id=old.id; END"
            )
        )
        conn.execute(
            text(
                f"CREATE TRIGGER trg_{FTS_TABLE}_update AFTER UPDATE ON papers BEGIN "
                f"DELETE FROM {FTS_TABLE} WHERE paper_id=old.id; "
                f"INSERT INTO {FTS_TABLE}(paper_id,user_id,title,authors,abstract,full_text) "
                "VALUES (new.id,new.user_id,coalesce(new.title,''),coalesce(new.authors,''),"
                "coalesce(new.abstract,''),coalesce(new.full_text,'')); END"
            )
        )
        fts_count = conn.execute(text(f"SELECT count(*) FROM {FTS_TABLE}")).scalar() or 0
        paper_count = conn.execute(text("SELECT count(*) FROM papers")).scalar() or 0
        if fts_count == 0 and paper_count:
            conn.execute(
                text(
                    f"INSERT INTO {FTS_TABLE}(paper_id,user_id,title,authors,abstract,full_text) "
                    "SELECT id,user_id,coalesce(title,''),coalesce(authors,''),"
                    "coalesce(abstract,''),coalesce(full_text,'') FROM papers"
                )
            )


def _fts_query(query: str) -> str:
    """把用户输入转成安全的 FTS5 MATCH 表达式。"""
    parts: list[str] = []
    for token in re.findall(r'"[^"]+"|\S+', (query or "").strip()):
        token = token.strip()
        if not token:
            continue
        if token.startswith('"') and token.endswith('"') and len(token) > 2:
            parts.append(token)
            continue
        token = re.sub(r'["*()\-\^]', " ", token)
        for word in token.split():
            if word:
                parts.append('"' + word.replace('"', '""') + '"')
    return " AND ".join(parts) or '""'


def fts_search(
    db: Session,
    query: str,
    user_id=None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """全文搜索论文，返回 {total, items}。"""
    if not _is_sqlite() or not (query or "").strip():
        return {"total": 0, "items": []}
    q = _fts_query(query)
    try:
        total = db.execute(
            text(
                f"SELECT count(*) FROM {FTS_TABLE} "
                f"WHERE {FTS_TABLE} MATCH :q AND user_id=:uid"
            ),
            {"q": q, "uid": str(user_id)},
        ).scalar() or 0
        rows = db.execute(
            text(
                f"SELECT p.id, p.title, p.year, p.authors, p.source, p.status, p.doi, "
                f"snippet({FTS_TABLE}, 5, '[', ']', '…', 16) AS snippet, "
                f"bm25({FTS_TABLE}) AS rank "
                f"FROM {FTS_TABLE} JOIN papers p ON p.id = {FTS_TABLE}.paper_id "
                f"WHERE {FTS_TABLE} MATCH :q AND {FTS_TABLE}.user_id=:uid "
                f"ORDER BY rank LIMIT :limit OFFSET :offset"
            ),
            {"q": q, "uid": str(user_id), "limit": int(limit), "offset": int(offset)},
        ).mappings().all()
    except Exception:  # noqa: BLE001
        return {"total": 0, "items": []}

    items = []
    for r in rows:
        authors = r["authors"]
        if isinstance(authors, str):
            try:
                import json
                authors = json.loads(authors)
            except (ValueError, TypeError):
                authors = []
        items.append(
            {
                "paper_id": str(r["id"]),
                "title": r["title"],
                "year": r["year"],
                "authors": authors or [],
                "source": r["source"],
                "status": r["status"],
                "doi": r["doi"],
                "snippet": r["snippet"] or "",
            }
        )
    return {"total": total, "items": items}
