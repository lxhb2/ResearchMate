"""顶层 Agent 联网搜索自动识别测试。"""

from app.agent.tools import _clean_search_query
from app.agent.top_agent import _wants_web_search


def test_search_topic_triggers_web_search():
    assert _wants_web_search("搜索陶瓷材料相关的学术名词") is True
    assert _wants_web_search("查一下最新锂电材料进展") is True


def test_clean_search_query_removes_conversational_intent():
    assert _clean_search_query("搜索陶瓷材料相关的学术名词") == "陶瓷材料"


def test_library_search_stays_local():
    assert _wants_web_search("搜索文献库中的陶瓷材料论文") is False
    assert _wants_web_search("检索相关论文") is False
