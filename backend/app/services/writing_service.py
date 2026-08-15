"""Writing assistant service: generate titles, outlines, drafts, abstracts, and find materials."""
import json
from uuid import UUID
from typing import Optional

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.paper_chunk import PaperChunk
from app.services import llm_service, search_service


def generate_titles(db: Session, user_id, direction: str) -> list[str]:
    system = (
        "You are an academic writing advisor. Given a research direction, propose 3 concrete, "
        "scholarly paper titles. Return ONLY a JSON object: {\"titles\": [\"...\", \"...\", \"...\"]}."
    )
    messages = llm_service.system_user(system, direction)
    data = llm_service.chat_json(db, user_id, messages, temperature=0.7)
    return data.get("titles", [])[:3]


def generate_outline(db: Session, user_id, topic: str, notes: Optional[str] = None) -> dict:
    system = (
        "You are an academic writing advisor. Generate a structured IMRaD-style paper outline for the given topic. "
        "Return ONLY JSON in this exact shape:\n"
        '{"sections": [{"title": "Introduction", "points": ["point 1", "point 2"]}, ...]}\n'
        "Include sections: Introduction, Related Work, Methods, Results, Discussion, Conclusion."
    )
    user = f"Topic: {topic}\n"
    if notes:
        user += f"Additional notes: {notes}"
    messages = llm_service.system_user(system, user)
    return llm_service.chat_json(db, user_id, messages, temperature=0.5)


def search_materials(db: Session, user_id, section_titles: list[str], top_k: int = 5) -> dict:
    """For each section title, run a semantic search and collect recommended chunks."""
    result = {}
    for title in section_titles:
        hits = search_service.semantic_search(db, query=title, top_k=top_k, user_id=user_id)
        result[title] = [
            {
                "chunk_id": str(h["chunk_id"]),
                "paper_id": str(h["paper_id"]),
                "paper_title": h["paper_title"],
                "dimension": h["dimension"],
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
        return _generate_section(db, user_id, sec, materials_text)

    # Generate all sections
    out_parts = []
    for sec in sections:
        out_parts.append(_generate_section(db, user_id, sec, materials_text))
    return "\n\n".join(out_parts)


def _generate_section(db: Session, user_id, section: dict, materials_text: str) -> str:
    title = section.get("title", "Section")
    points = section.get("points", [])
    points_str = "\n".join(f"- {p}" for p in points) if points else "(no specific points)"

    system = (
        "You are an academic writing assistant. Write a coherent, well-developed section of an academic paper "
        "in Markdown. Use the provided outline points and reference materials. "
        "Begin with a level-2 Markdown heading (## Section Title). Write in formal academic English. "
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


def generate_abstract(db: Session, user_id, content: str) -> dict:
    system = (
        "You are an academic writing assistant. Based on the full paper draft, generate a concise abstract "
        "(150-250 words) and 5 keywords. Return ONLY JSON: "
        '{"abstract": "...", "keywords": ["...", "...", "...", "...", "..."]}.'
    )
    messages = llm_service.system_user(system, content[:12000])
    return llm_service.chat_json(db, user_id, messages, temperature=0.4)
