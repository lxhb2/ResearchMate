"""Writing assistant service: generate titles, outlines, drafts, abstracts, and find materials."""
import json
from uuid import UUID
from typing import Optional

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.paper_chunk import PaperChunk
from app.services import llm_service, search_service
from app.services import writing_guide


def generate_titles(db: Session, user_id, direction: str, language: str = "zh") -> list[str]:
    lang_label = "中文" if language != "en" else "English"
    system = (
        f"You are an academic writing advisor. Given a research direction, propose 3 concrete, "
        f"scholarly paper titles in {lang_label}. "
        "Titles should be predictive, specific, and consistent with the paper content. "
        'Return ONLY a JSON object: {"titles": ["...", "...", "..."]}.'
    )
    user = f"Research direction: {direction}\n\nTitle language: {lang_label}"
    messages = llm_service.system_user(system, user)
    data = llm_service.chat_json(db, user_id, messages, temperature=0.7)
    return data.get("titles", [])[:3]


def generate_outline(
    db: Session,
    user_id,
    topic: str,
    notes: Optional[str] = None,
    language: str = "zh",
) -> dict:
    sections_hint = " / ".join(writing_guide.outline_sections(language))
    system = (
        f"You are an academic writing advisor. Generate a structured IMRaD-style paper outline for the given topic. "
        f"Suggested sections: {sections_hint}. Use the target language for section titles and points. "
        f"{writing_guide.writing_guidance(language)} "
        "Return ONLY JSON in this exact shape:\n"
        '{"sections": [{"title": "Introduction", "points": ["point 1", "point 2"]}, ...]}\n'
        "Do not include a top-level document title."
    )
    user = f"Topic: {topic}\n"
    if notes:
        user += f"Additional notes: {notes}"
    messages = llm_service.system_user(system, user)
    return llm_service.chat_json(db, user_id, messages, temperature=0.5)


def search_materials(db: Session, user_id, section_titles: list[str], top_k: int = 5) -> dict:
    """For each section title, run a dimension-aware semantic search on the 6-dim vector library."""
    result = {}
    for title in section_titles:
        dimension = writing_guide.dimension_for_section(title)
        hits = search_service.semantic_search(
            db,
            query=title,
            top_k=top_k,
            dimension=dimension,
            user_id=user_id,
        )
        result[title] = [
            {
                "chunk_id": str(h["chunk_id"]),
                "paper_id": str(h["paper_id"]),
                "paper_title": h["paper_title"],
                "dimension": h["dimension"],
                "dimension_label": search_service.DIMENSION_LABELS.get(h["dimension"], h["dimension"]),
                "content": h["content"],
                "score": h["score"],
            }
            for h in hits
        ]
    return result


def generate_draft(
    db: Session,
    user_id,
    outline: dict,
    material_chunk_ids: list[UUID],
    section: Optional[str] = None,
    language: str = "zh",
) -> str:
    # Gather material texts
    materials_text = ""
    if material_chunk_ids:
        chunks = db.query(PaperChunk).filter(PaperChunk.id.in_(material_chunk_ids)).all()
        parts = []
        for c in chunks:
            parts.append(f"[{c.dimension}] {c.content}")
        materials_text = "\n\n".join(parts)

    sections = outline.get("sections", []) if isinstance(outline, dict) else []

    if section:
        # Generate a single section
        sec = next((s for s in sections if s.get("title") == section), None)
        if not sec:
            sec = {"title": section, "points": []}
        return _generate_section(db, user_id, sec, materials_text, language)

    # Generate all sections
    out_parts = []
    for sec in sections:
        out_parts.append(_generate_section(db, user_id, sec, materials_text, language))
    return "\n\n".join(out_parts)


def _generate_section(
    db: Session,
    user_id,
    section: dict,
    materials_text: str,
    language: str = "zh",
) -> str:
    title = section.get("title", "Section")
    points = section.get("points", [])
    points_str = "\n".join(f"- {p}" for p in points) if points else "(no specific points)"

    system = (
        "You are an academic writing assistant. Write a coherent, well-developed section of an academic paper "
        f"in Markdown. {writing_guide.writing_guidance(language)} "
        "Use the provided outline points and reference materials. "
        "Begin with a level-2 Markdown heading (## Section Title). "
        "Cite referenced materials inline as (Author, Year) where inferable; otherwise omit. "
        "Do not include a top-level document title."
    )
    user = (
        f"Section title: {title}\n"
        f"Outline points:\n{points_str}\n\n"
        f"Reference materials:\n{materials_text or 'No materials provided.'}\n\n"
        f"Write the {title} section now."
    )
    messages = llm_service.system_user(system, user)
    text = llm_service.chat(db, user_id, messages, temperature=0.5, max_tokens=1500)
    # Ensure heading exists
    if not text.strip().startswith("#"):
        text = f"## {title}\n\n" + text
    return text.strip()


def generate_abstract(db: Session, user_id, content: str, language: str = "zh") -> dict:
    lang_label = "中文" if language != "en" else "English"
    system = (
        f"You are an academic writing assistant. {writing_guide.abstract_guidance(language)} "
        f"Generate the abstract and keywords in {lang_label}. Return ONLY JSON: "
        '{"abstract": "...", "keywords": ["...", "...", "...", "...", "..."]}.'
    )
    messages = llm_service.system_user(system, content[:12000])
    return llm_service.chat_json(db, user_id, messages, temperature=0.4)


def generate_abstracts(db: Session, user_id, content: str) -> dict:
    """同时生成中英文摘要与关键词（国内论文摘要要求双语）。"""
    return {
        "zh": generate_abstract(db, user_id, content, language="zh"),
        "en": generate_abstract(db, user_id, content, language="en"),
    }
