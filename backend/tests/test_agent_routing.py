"""顶层 Agent 联网搜索自动识别测试。"""

from app.agent.tools import _clean_search_query
from app.agent.top_agent import _wants_web_search, TopAgent
from app.agent.specialized import AcademicResearchAgent, is_academic_research
from app.agent.tools import ToolContext


def test_search_topic_triggers_web_search():
    assert _wants_web_search("搜索陶瓷材料相关的学术名词") is True
    assert _wants_web_search("查一下最新锂电材料进展") is True


def test_clean_search_query_removes_conversational_intent():
    assert _clean_search_query("搜索陶瓷材料相关的学术名词") == "陶瓷材料"


def test_library_search_stays_local():
    assert _wants_web_search("搜索文献库中的陶瓷材料论文") is False
    assert _wants_web_search("检索相关论文") is False


class _FakeTool:
    def __init__(self, result):
        self.result = result

    def run(self, ctx, args):
        return self.result


def test_academic_research_agent_combines_local_and_web(monkeypatch):
    local_result = {
        "count": 1,
        "hits": [{"paper_id": "p1", "paper_title": "Local Paper", "dimension": "method", "content": "local evidence"}],
    }
    web_result = {
        "count": 1,
        "mode": "academic",
        "providers": ["openalex", "crossref"],
        "items": [{"title": "Web Paper", "url": "https://doi.org/10.1000/example", "snippet": "web evidence"}],
    }

    def fake_get_tool(name):
        if name == "rag_search":
            return _FakeTool(local_result)
        if name == "web_search":
            return _FakeTool(web_result)
        return None

    monkeypatch.setattr("app.agent.specialized.get_tool", fake_get_tool)
    agent = AcademicResearchAgent(ToolContext(llm=None, mock=True))
    out = agent.handle("帮我综述多模态大模型研究进展")

    assert out["route_label"] == "学术研究助手"
    assert out["local_materials_count"] == 1
    assert out["web_materials_count"] == 1
    assert out["academic_sources"] == ["openalex", "crossref"]
    assert [t["tool"] for t in out["tool_trace"]] == ["rag_search", "web_search"]
    assert "Local Paper" in out["answer"]
    assert "Web Paper" in out["answer"]


def test_explicit_web_search_with_review_request_routes_academic_agent():
    agent = TopAgent(db=None, user_id="user-1", mock=True)
    assert agent.route("帮我综述大模型研究进展", web_search=True)["path"] == "academic_research"
    assert is_academic_research("帮我综述大模型研究进展") is True
