"""标注/笔记导出：Markdown / JSON / Zotero RDF。"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.paper import Paper


def _rows(db: Session, user_id, paper_id: Optional[str]) -> list[tuple[Annotation, Paper]]:
    q = (
        db.query(Annotation, Paper)
        .join(Paper, Annotation.paper_id == Paper.id)
        .filter(Annotation.user_id == user_id)
    )
    if paper_id:
        q = q.filter(Annotation.paper_id == paper_id)
    return q.order_by(Paper.title.asc(), Annotation.page_number.asc(), Annotation.created_at.asc()).all()


def _item(ann: Annotation, paper: Paper) -> dict:
    return {
        "paper_id": str(paper.id),
        "paper_title": paper.title,
        "type": ann.type,
        "page": ann.page_number,
        "snippet": ann.content or "",
        "note": ann.comment or "",
        "tags": ann.tags or [],
        "color": ann.color,
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
    }


def export_annotations(
    db: Session,
    user_id,
    paper_id: Optional[str] = None,
    fmt: str = "md",
) -> tuple[str, str, str]:
    """返回 (内容, 文件名, media_type)。"""
    rows = _rows(db, user_id, paper_id)
    items = [_item(a, p) for a, p in rows]
    if fmt == "json":
        return json.dumps(items, ensure_ascii=False, indent=2), "researchmate-annotations.json", "application/json"
    if fmt == "rdf":
        return _to_rdf(items), "researchmate-annotations.rdf", "application/rdf+xml"
    return _to_markdown(items), "researchmate-annotations.md", "text/markdown; charset=utf-8"


def _to_markdown(items: list[dict]) -> str:
    lines = ["# ResearchMate 文献标注与笔记", ""]
    if not items:
        lines.append("（暂无标注）")
        return "\n".join(lines)
    current = None
    for it in items:
        title = it.get("paper_title") or "未命名"
        if title != current:
            lines.extend([f"## {title}", ""])
            current = title
        page = f"（p. {it['page']}）" if it.get("page") else ""
        lines.append(f"### {it.get('type')} {page}")
        if it.get("snippet"):
            lines.append(f"> {it['snippet']}")
        if it.get("note"):
            lines.append(f"笔记：{it['note']}")
        if it.get("tags"):
            lines.append(f"标签：{', '.join(it['tags'])}")
        lines.append("")
    return "\n".join(lines)


def _to_rdf(items: list[dict]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:z="http://www.zotero.org/namespaces/export#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">',
    ]
    for i, it in enumerate(items, 1):
        note = it.get("note") or it.get("snippet") or ""
        title = f"{it.get('paper_title') or 'Annotation'} - {it.get('type')}"
        lines.append(f'  <rdf:Description rdf:about="annotation-{i}">')
        lines.append("    <z:itemType>note</z:itemType>")
        lines.append(f"    <z:title><![CDATA[{title}]]></z:title>")
        if it.get("page"):
            lines.append(f"    <z:note><![CDATA[p. {it['page']}\n\n{note}]]></z:note>")
        else:
            lines.append(f"    <z:note><![CDATA[{note}]]></z:note>")
        lines.append("  </rdf:Description>")
    lines.append("</rdf:RDF>")
    return "\n".join(lines)
