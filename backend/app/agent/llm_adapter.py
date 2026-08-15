"""LLM 兼容层（基于 LiteLLM）。

目标：让 Agent / 工具在调用大模型时，可以无缝切换 OpenAI 兼容接口、本地
Ollama 模型，或离线 Mock 模式（用于演示与测试，无需真实 API Key）。

设计借鉴 DeepSeek Harness 将 LLM 调用与业务解耦的思想，但为独立实现。
"""
import json
import re
from typing import Any, Optional

import litellm

# 关闭 litellm 的遥测/自定义日志，保持轻量
litellm.telemetry = False
litellm.drop_params = True


class LLMProvider:
    """使用的后端 provider 常量。"""
    OPENAI = "openai"      # OpenAI 协议兼容（国内大模型通用）
    OLLAMA = "ollama"      # 本地 Ollama
    MOCK = "mock"          # 离线假模型，用于演示/测试


class LLMAdapter:
    """封装对上游大模型的调用，统一 chat / chat_json 接口。"""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: str = LLMProvider.OPENAI,
    ):
        self.model = model
        self.api_key = api_key or "sk-placeholder"
        self.base_url = base_url
        self.provider = provider

    # ---- 工厂方法 ----

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "LLMAdapter":
        """根据设置字典构造适配器（provider 自动推断）。

        cfg 形如 {"api_key","base_url","model"}，来自 settings_service.get_llm_config。
        """
        base_url = (cfg.get("base_url") or "").strip()
        model = (cfg.get("model") or "gpt-4o").strip()
        api_key = (cfg.get("api_key") or "").strip()

        # 本地 Ollama：base_url 含 ollama 关键字
        if "ollama" in base_url.lower():
            return cls(model=model, api_key=api_key, base_url=base_url, provider=LLMProvider.OLLAMA)
        # 显式 mock 模式
        if model == "mock" or "mock" in base_url.lower():
            return cls(model=model, api_key=api_key, base_url=base_url, provider=LLMProvider.MOCK)
        return cls(model=model, api_key=api_key, base_url=base_url, provider=LLMProvider.OPENAI)

    @classmethod
    def mock(cls) -> "LLMAdapter":
        """构造一个离线 Mock 适配器，便于演示测试。"""
        return cls(model="mock", provider=LLMProvider.MOCK)

    # ---- LiteLLM 模型名 ----

    def _completion_model(self) -> str:
        """拼出 LiteLLM 需要的模型名（provider 前缀）。"""
        if self.provider == LLMProvider.OLLAMA:
            return f"ollama/{self.model}"
        return f"openai/{self.model}"

    # ---- 核心调用 ----

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        """同步对话补全，返回助手文本。"""
        if self.provider == LLMProvider.MOCK:
            return self._mock_chat(messages, json_mode=json_mode)

        kwargs: dict[str, Any] = dict(
            model=self._completion_model(),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=self.api_key,
        )
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if json_mode:
            # 部分模型不支持 response_format，litellm 里设置 drop_params 后会自动忽略
            kwargs["response_format"] = {"type": "json_object"}

        resp = litellm.completion(**kwargs)
        return resp.choices[0].message.content or ""

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.3,
    ) -> dict:
        """调用模型并把响应解析为 JSON 对象。"""
        text = self.chat(messages, temperature=temperature, json_mode=True)
        return self.parse_json(text)

    @staticmethod
    def parse_json(text: str) -> dict:
        """健壮地解析模型输出中的 JSON（兼容代码块包裹）。"""
        text = (text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试截取第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"无法从模型输出解析 JSON: {text[:200]}")

    # ---- Mock 实现（离线确定性响应）----

    def _mock_chat(self, messages: list[dict], json_mode: bool = False) -> str:
        """根据系统提示词中的关键词返回固定的示例响应，保证离线可演示。"""
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")

        if "工作流" in system or "workflow" in system.lower():
            return json.dumps(self._mock_workflow(user), ensure_ascii=False)
        if "翻译" in system or "translate" in system.lower():
            return "（Mock 翻译）这是对摘要的中文翻译示例文本，用于演示翻译工具已被调用。"
        if "对比" in system or "compare" in system.lower():
            return json.dumps(self._mock_compare(), ensure_ascii=False)
        if "参考文献" in system or "citation" in system.lower() or "GB7714" in system:
            return json.dumps(self._mock_citation(), ensure_ascii=False)
        # 兜底
        return "（Mock 响应）已收到请求。"

    def _mock_workflow(self, user: str) -> dict:
        """返回与示例指令配套的确定性工作流。"""
        return {
            "workflow_id": "wf_demo_001",
            "name": "文献导入-翻译-对比-写入 流水线",
            "description": (
                "任务拆解：1) 解析新导入论文获取摘要；2) 翻译摘要；"
                "3) 检索我标记重点的文献；4) 与标记文献做方法对比；"
                "5) 将对比表格写入写作项目。"
            ),
            "start": "n1",
            "nodes": {
                "n1": {
                    "id": "n1", "type": "tool", "tool": "paper_parse",
                    "description": "解析新导入论文，取出摘要", "retry": 1,
                    "args": {"source": "latest"}, "next": "n2",
                },
                "n2": {
                    "id": "n2", "type": "tool", "tool": "llm_translate",
                    "description": "翻译论文摘要", "args": {"target_lang": "zh"}, "next": "n3",
                },
                "n3": {
                    "id": "n3", "type": "tool", "tool": "rag_search",
                    "description": "检索我标记重点的文献片段", "retry": 1,
                    "args": {"query": "我标记重点的文献", "top_k": 3, "highlighted_only": True},
                    "next": "n4",
                },
                "n4": {
                    "id": "n4", "type": "condition",
                    "description": "判断是否检索到重点文献",
                    "condition": {"variable": "results.n3.count", "operator": ">", "value": 0},
                    "next_if_true": "n5", "next_if_false": "n6",
                },
                "n5": {
                    "id": "n5", "type": "tool", "tool": "llm_compare",
                    "description": "与标记文献做方法对比，生成对比表格",
                    "args": {"query": "我标记重点的文献", "dimensions": ["method", "conclusion"]},
                    "next": "n7",
                },
                "n6": {
                    "id": "n6", "type": "confirm",
                    "description": "未检索到重点文献，请确认是否继续", "next": "n7",
                },
                "n7": {
                    "id": "n7", "type": "tool", "tool": "note_append",
                    "description": "将对比表格写入写作项目",
                    "args": {"project_id": "auto", "content": "$results.n5.output"}, "next": "n8",
                },
                "n8": {"id": "n8", "type": "end", "description": "完成"},
            },
            "output": "n7",
        }

    def _mock_compare(self) -> dict:
        return {
            "table": "| 维度 | 新论文 | 文献A | 文献B |\n|------|--------|-------|-------|\n| 方法 | 方法X | 方法Y | 方法Z |",
            "summary": "（Mock 对比）三篇文献在方法上各有侧重。",
        }

    def _mock_citation(self) -> dict:
        return {
            "references": [
                "[1] 张三, 李四. 论文标题[J]. 期刊名, 2023, 10(2): 100-110.",
                "[2] Wang, L., & Zhang, S. Title of paper[J]. Journal, 2022, 8(1): 20-30.",
            ]
        }