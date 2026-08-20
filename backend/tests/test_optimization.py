"""Agent 记忆/事件流与 P2 基础能力测试。"""
import uuid

from app.agent import memory as memory_mod
from app.agent.top_agent import TopAgent
from app.database import SessionLocal
from app.services import export_service, glossary_service, reflection_service, task_queue, writing_guide
from app.services import translation_cache


def test_glossary_crud() -> None:
    uid = f"glossary-{uuid.uuid4().hex[:8]}"
    item = glossary_service.add_term(uid, "Transformer", definition="注意力机制架构", translation="Transformer 模型")
    assert glossary_service.list_terms(uid)[0]["term"] == "Transformer"
    assert glossary_service.search_terms(uid, "transformer")
    assert glossary_service.delete_term(uid, item["id"]) is True
    assert glossary_service.list_terms(uid) == []


def test_event_stream_yields_answer_with_mock() -> None:
    agent = TopAgent(db=None, user_id="event-user", mock=True)
    events = list(agent.event_stream("你好"))
    types = [e["type"] for e in events]
    assert "route" in types
    assert "thinking" in types
    assert "answer" in types


def test_reflection_saves_to_memory() -> None:
    uid = f"reflect-{uuid.uuid4().hex[:8]}"
    memory_mod.ensure_exists(uid)
    reflection_service.save_reflection(
        uid,
        "测试反思",
        "检索并整理文献",
        "完成检索，得到 3 篇关键文献",
        "success",
    )
    content = memory_mod.read_memory(uid, "notes.md")
    assert "测试反思" in content
    assert "3 篇关键文献" in content


def test_session_summary_task_skips_without_llm() -> None:
    with SessionLocal() as db:
        task = task_queue.enqueue(
            db,
            "summary-user",
            "conversation_summary",
            {"messages": [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好，有什么可以帮你？"}]},
        )
        result = task_queue._dispatch(task)
    assert result.get("skipped") is True


def test_printable_html_export() -> None:
    html = export_service.md_to_printable_html("## 标题\n\n| A | B |\n|---|---|\n| 1 | 2 |", "测试")
    text = html.decode("utf-8")
    assert "<h2>标题</h2>" in text
    assert "<table>" in text


def test_writing_guide_dimension_mapping() -> None:
    assert writing_guide.dimension_for_section("Methods") == "method"
    assert writing_guide.dimension_for_section("引言") == "background"
    assert writing_guide.dimension_for_section("Results") == "results"
    assert "IMRaD" in writing_guide.writing_guidance("en")
    assert "目的" in writing_guide.abstract_guidance("zh")


def test_cluster_nebula_layout_separates_clusters() -> None:
    from app.services import graph_service

    pts = [[float(i), float(i % 3)] for i in range(20)]
    labels = [0] * 10 + [1] * 10
    layout = graph_service._cluster_nebula_layout(pts, labels, 2, canvas=2600)
    c0 = [layout[i] for i in range(10)]
    c1 = [layout[i] for i in range(10, 20)]
    cx0 = sum(p[0] for p in c0) / 10
    cy0 = sum(p[1] for p in c0) / 10
    cx1 = sum(p[0] for p in c1) / 10
    cy1 = sum(p[1] for p in c1) / 10
    dist = ((cx0 - cx1) ** 2 + (cy0 - cy1) ** 2) ** 0.5
    assert dist > 500


def test_translation_cache_roundtrip() -> None:
    translation_cache.set("auto", "zh", "Transformer", "Transformer 模型")
    assert translation_cache.get("auto", "zh", "Transformer") == "Transformer 模型"
    assert translation_cache.get("auto", "en", "Transformer") is None
