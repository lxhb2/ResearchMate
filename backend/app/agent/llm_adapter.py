"""LLM 兼容层（基于 LiteLLM）。

目标：让 Agent / 工具在调用大模型时，可以无缝切换 OpenAI 兼容接口、本地
Ollama 模型，或离线 Mock 模式（用于演示与测试，无需真实 API Key）。

设计借鉴 DeepSeek Harness 将 LLM 调用与业务解耦的思想，但为独立实现。
"""
import json
import re
import time
from datetime import datetime
from typing import Any, Optional

import httpx
import litellm

# 关闭 litellm 的遥测/自定义日志，保持轻量
litellm.telemetry = False
litellm.drop_params = True

# 超时策略：连接超时短（服务不可达时快速失败降级），
# 读取超时长（真实 LLM 生成一次回答常需 10-60 秒）。
# 注意不能设单一短总超时：否则「配置完全正确」的调用也会因生成耗时
# 被判为连接失败并触发熔断，造成配置正确却持续降级的误报。
LLM_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)

# 熔断窗口（秒）：上游连接失败后，短时间内同一配置的请求直接降级 mock，
# 不再每个请求都等一次完整超时（翻译/问答高频调用时体验差异巨大）。
_CIRCUIT_BREAK_SECONDS = 60
# 熔断状态：(base_url|model) -> 失败时刻
_circuit_open: dict[str, float] = {}
# 最近一次失败原因：(base_url|model) -> 简短描述（用于降级提示自诊断）
_circuit_errors: dict[str, str] = {}
_circuit_lock = __import__("threading").Lock()


def _breaker_key(base_url: str, model: str) -> str:
    return f"{(base_url or '').rstrip('/')}|{model}"


def _is_circuit_open(base_url: Optional[str], model: str) -> bool:
    key = _breaker_key(base_url or "", model)
    with _circuit_lock:
        t = _circuit_open.get(key)
        return t is not None and (time.time() - t) < _CIRCUIT_BREAK_SECONDS


def _trip_breaker(base_url: Optional[str], model: str, reason: str = "") -> None:
    with _circuit_lock:
        _circuit_open[_breaker_key(base_url or "", model)] = time.time()
        if reason:
            _circuit_errors[_breaker_key(base_url or "", model)] = reason


def _last_error(base_url: Optional[str], model: str) -> str:
    with _circuit_lock:
        return _circuit_errors.get(_breaker_key(base_url or "", model), "")


def _reset_breaker(base_url: Optional[str], model: str) -> None:
    with _circuit_lock:
        _circuit_open.pop(_breaker_key(base_url or "", model), None)
        _circuit_errors.pop(_breaker_key(base_url or "", model), None)


def reset_breakers() -> None:
    """清空全部熔断状态。

    保存新配置后调用：否则旧的熔断记录（按 base_url|model 索引）会让
    「刚改完配置立刻重试」的请求继续直接降级，用户误以为新配置无效。
    """
    with _circuit_lock:
        _circuit_open.clear()
        _circuit_errors.clear()


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
        """同步对话补全，返回助手文本。

        上游不可达 / Key 无效等连接类错误：快速失败并降级为 mock 响应，
        保证功能链路始终有输出（前端不再出现 500 或长时间转圈）。
        含熔断：一次连接失败后 60s 内直接降级，不再重复等待超时。
        """
        if self.provider == LLMProvider.MOCK:
            return self._mock_chat(messages, json_mode=json_mode)
        if _is_circuit_open(self.base_url, self.model):
            return self._mock_chat(
                messages, json_mode=json_mode, degraded=True,
                reason=_last_error(self.base_url, self.model),
            )

        kwargs: dict[str, Any] = dict(
            model=self._completion_model(),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=self.api_key,
            timeout=LLM_TIMEOUT,
            num_retries=0,  # 不可达时快速失败降级，避免 litellm 默认重试拖慢响应
        )
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if json_mode:
            # 部分模型不支持 response_format，litellm 里设置 drop_params 后会自动忽略
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = litellm.completion(**kwargs)
            _reset_breaker(self.base_url, self.model)
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            reason = self._degrade_reason(e)
            if reason is not None:
                _trip_breaker(self.base_url, self.model, reason)
                return self._mock_chat(
                    messages, json_mode=json_mode, degraded=True, reason=reason,
                )
            raise

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ):
        """流式对话补全，逐 token 产出文本片段（生成器）。

        用于 SSE 场景：让用户尽快看到首字，边生成边显示，显著降低感知延迟。
        上游不可达时降级为 mock 流（带降级说明），不再抛异常。
        含熔断：一次连接失败后 60s 内直接降级，不再重复等待超时。
        """
        if self.provider == LLMProvider.MOCK:
            text = self._mock_chat(messages)
            # 分块产出，模拟真实 token 流，便于前端流式渲染演示
            # 加小幅延迟，让浏览器能直观看到文本逐段渐进出现
            for i in range(0, len(text), 6):
                yield text[i : i + 6]
                time.sleep(0.03)
            return
        if _is_circuit_open(self.base_url, self.model):
            text = self._mock_chat(
                messages, degraded=True,
                reason=_last_error(self.base_url, self.model),
            )
            for i in range(0, len(text), 6):
                yield text[i : i + 6]
                time.sleep(0.03)
            return

        kwargs: dict[str, Any] = dict(
            model=self._completion_model(),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=self.api_key,
            stream=True,
            timeout=LLM_TIMEOUT,
            num_retries=0,  # 不可达时快速失败降级，避免 litellm 默认重试拖慢响应
        )
        if self.base_url:
            kwargs["api_base"] = self.base_url

        try:
            resp = litellm.completion(**kwargs)
            _reset_breaker(self.base_url, self.model)
        except Exception as e:  # noqa: BLE001
            reason = self._degrade_reason(e)
            if reason is not None:
                _trip_breaker(self.base_url, self.model, reason)
                text = self._mock_chat(messages, degraded=True, reason=reason)
                for i in range(0, len(text), 6):
                    yield text[i : i + 6]
                    time.sleep(0.03)
                return
            raise
        for chunk in resp:
            # litellm 流式 chunk：choices[0].delta.content
            try:
                delta = chunk["choices"][0]["delta"]
                token = delta.get("content")
            except (KeyError, IndexError, TypeError):
                token = None
            if token:
                yield token

    @staticmethod
    def _degrade_reason(e: Exception) -> Optional[str]:
        """判断是否为「配置/网络类」错误（可安全降级 mock）。

        返回给用户看的简短失败原因；返回 None 表示其他业务异常，照常抛出。
        """
        try:
            if isinstance(e, litellm.AuthenticationError):
                return "认证失败（401）：API Key 无效、过期或未授权"
            if isinstance(e, litellm.NotFoundError):
                return "接口返回 404：Base URL 可能填写错误（如缺少或多余 /v1）"
            if isinstance(e, litellm.PermissionDeniedError):
                return "无权限（403）：该 Key 无权访问此模型"
            if isinstance(e, litellm.APIConnectionError):
                return "无法连接到服务：网络不通、地址错误或服务不可达"
        except AttributeError:
            pass
        name = type(e).__name__
        lname = name.lower()
        text = str(e).lower()
        if "timeout" in text or "timed out" in text or "timeout" in lname:
            return "连接超时：服务不可达或网络受限"
        if "api key" in text or "unauthorized" in text or "401" in text or "apikey" in lname:
            return "认证失败：API Key 无效或未授权"
        if "connection" in text or "connection" in lname:
            return "无法连接到服务：网络不通、地址错误或服务不可达"
        if "model" in text and ("not found" in text or "does not exist" in text):
            return "模型不存在：请检查模型名称是否为该厂商支持的 ID"
        return None

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

    def _mock_chat(self, messages: list[dict], json_mode: bool = False, degraded: bool = False, reason: str = "") -> str:
        """根据系统提示词中的关键词返回场景化的示例响应，保证离线可演示。

        degraded=True 表示「配置了真实 LLM 但服务不可达」的降级响应，
        文案会明确提示当前为降级输出、失败原因与配置指引。
        """
        system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        # 场景识别只看 system 的「角色定义区」（前 300 字符）：
        # 业务路由会把论文全文拼进 system/user，全文里的「对比/翻译」等普通词
        # 不能误触发对应 mock 场景。按特异性从高到低匹配。
        head = system[:300].lower()
        # 用户消息里去掉 Prompt 模板噪音（如 "Paper text:" 前缀）
        question = user.strip().splitlines()[0][:60] if user.strip() else ""
        ts = datetime.now().strftime("%H:%M:%S")

        notice = (
            f"> ⚠️ 当前为**离线降级响应**（{ts}）：未能连接到所配置的大模型服务。\n"
            + (f"> 失败原因：**{reason}**\n" if reason else "")
            + "> 请到「设置」页确认 API 地址 / Key / 模型填写正确并保存（保存后立即生效），或稍后重试。\n\n"
            if degraded
            else ""
        )

        if "工作流" in head or "workflow" in head:
            return json.dumps(self._mock_workflow(user), ensure_ascii=False)
        if "translator" in head:
            # 取被翻译文本的第一句做「回显式」译文，比纯占位文案更有用
            source = user.split("Text to translate:", 1)[-1].strip()
            head_line = next((ln for ln in source.splitlines() if ln.strip()), "")[:120]
            return (
                f"{notice}"
                f"【译文（离线）】{head_line}\n\n"
                "（当前未连接大模型服务，以上为原文回显。配置 API 后将返回真正的 AI 翻译，"
                "专业术语会按学术语境准确处理。）"
            )
        if "glossary" in head or "术语" in head:
            term = user.split("Term to explain:", 1)[-1].strip()[:60]
            return (
                f"{notice}"
                f"**{term}**（离线解释）\n\n"
                "- **定义**：这是在离线模式下对术语的占位解释。\n"
                "- **领域**：取决于该术语出现的学科语境。\n"
                "- **用法示例**：请在「设置」页配置大模型接口后，重新划词解释以获得完整内容。"
            )
        if "literature review" in head:
            return self._mock_literature_review(user, notice, system)
        if "research assistant" in head:
            return (
                f"{notice}"
                f"已收到你关于论文的提问：「{question}」。\n\n"
                "当前未连接大模型服务，无法基于论文全文生成针对性回答。\n"
                "请在「设置」页配置可用的 OpenAI 兼容接口（地址 / Key / 模型）后重新提问，"
                "即可获得基于该论文内容的逐字流式回答。"
            )
        if "对比" in head or "compare" in head:
            return json.dumps(self._mock_compare(), ensure_ascii=False)
        if "参考文献" in head or "citation" in head or "gb7714" in head:
            return json.dumps(self._mock_citation(), ensure_ascii=False)
        # 兜底
        return (
            f"{notice}"
            f"已收到你的问题：「{question}」（{ts}）。\n\n"
            "当前为离线演示响应。配置大模型接口后，这里会由真实模型逐字生成内容，"
            "通过 SSE 流式推送，让你在回答生成的第一时间就看到首字出现。"
        )

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

    def _mock_literature_review(self, user: str, notice: str, system: str = "") -> str:
        """离线模式：生成一份可演示的综述，引用提示词中出现的片段别名（\\citation 标记）。

        提取 "[c1] (p. N)" 形式的片段别名，挑 2-4 个生成带引用标记的段落，
        保证离线也能看到「逐段 + 引用」的完整链路效果。
        """
        # 提取短别名与页码（格式与 _build_review_context 的提示词一致：[c1] (p. N)）
        pairs = re.findall(r"\[(c\d+)\] \(p\. (\d+)\)", user or "")
        seen: list[tuple[str, str]] = []
        for cid, page in pairs:
            if cid not in [s[0] for s in seen]:
                seen.append((cid, page))
        if not seen:
            seen = [("c1", "1")]
        topic = ""
        for ln in (user or "").splitlines() + (system or "").splitlines():
            if ln.strip().startswith("Research topic:"):
                topic = ln.split(":", 1)[-1].strip()
                break
        if not topic:
            topic = "该研究主题"
        cited = ",\\".join(cid for cid, _p in seen[:3])
        c1, p1 = seen[0]
        c2 = seen[1][0] if len(seen) > 1 else c1
        return (
            f"{notice}"
            f"## 关于「{topic}」的文献综述（离线演示）\n\n"
            f"### 1. 研究现状\n"
            f"近年来，围绕「{topic}」的研究逐渐增多。已有工作主要从方法设计与实验验证两条线索展开"
            f"，相关结论对后续研究具有重要参考价值。\\citation{{{cited}}}\n\n"
            f"### 2. 方法对比\n"
            f"不同研究在技术路径上各有侧重：部分工作强调端到端建模，另一些则关注模块化设计。"
            f"尽管实现细节不同，但在关键指标上都取得了一致的效果提升。\\citation{{{c1}}}\n\n"
            f"### 3. 研究空白\n"
            f"当前研究仍存在若干不足：一是缺乏跨数据集的可比性评价，二是对小规模样本的鲁棒性关注不够"
            f"（p. {p1}）。上述空白为后续工作提供了明确方向。\\citation{{{c1},{c2}}}\n\n"
            "> ⚠️ 以上为**离线演示综述**（内容为占位，非真实文献结论）。"
            "在「设置」页配置大模型接口后，将基于所选文献的真实内容生成带精确引用的综述。"
        )