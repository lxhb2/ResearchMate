"""本地大模型调用层：Ollama / OpenAI 兼容 / 离线确定性降级。

不强制联网，也不引入重型依赖：
- 优先尝试 litellm（若已安装，可统一走 OpenAI 协议与 Ollama）；
- 否则用标准库 urllib 直连 Ollama 的 /api/chat；
- 两者都不可用或未配置 Key 时，回退到离线 Mock 引擎，保证示例可跑通。
"""
import json
import urllib.request

from research_skills import config


class LLMError(RuntimeError):
    pass


class LLMClient:
    """极简 LLM 客户端，统一 chat() 接口。"""

    def __init__(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
        api_key: str = "",
    ):
        self.provider = (provider or config.LLM_PROVIDER or "auto").lower()
        self.model = model or config.OLLAMA_MODEL
        self.base_url = base_url or config.OLLAMA_BASE_URL
        self.api_key = api_key or config.OPENAI_API_KEY

        if self.provider == "auto":
            if self.api_key and self.api_key not in ("", "sk-xxx", "sk-sandbox-placeholder"):
                # 有真实 Key 时默认走 OpenAI 兼容
                self.provider = "openai"
                self.model = self.model or config.OPENAI_MODEL
                self.base_url = self.base_url if "ollama" not in self.base_url else config.OPENAI_BASE_URL
            elif "ollama" in self.base_url.lower():
                self.provider = "ollama"
            else:
                self.provider = "mock"

    # ---- 对外主接口 ----

    def chat(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 2048) -> str:
        """一次对话，返回助手文本。"""
        if self.provider == "mock":
            return self._mock(system, user)
        if self.provider == "ollama":
            return self._call_ollama(system, user)
        return self._call_openai(system, user, temperature, max_tokens)

    # ---- Ollama（标准库 urllib，无额外依赖）----

    def _call_ollama(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.3},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Ollama 调用失败: {exc}") from exc

    # ---- OpenAI 兼容（优先 litellm，其次原生 HTTP）----

    def _call_openai(self, system: str, user: str, temperature: float, max_tokens: int) -> str:
        try:
            import litellm  # type: ignore

            litellm.drop_params = True
            resp = litellm.completion(
                model=f"openai/{self.model}",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                api_key=self.api_key,
                api_base=self.base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=120,          # 不设时 litellm 默认 600s，服务不可达会长时间挂起
                num_retries=0,        # 不可达时快速失败，避免内部重试拖慢响应
            )
            return resp.choices[0].message.content or ""
        except ImportError:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001
                raise LLMError(f"OpenAI 兼容接口调用失败: {exc}") from exc

    # ---- 离线确定性降级 ----

    def _mock(self, system: str, user: str) -> str:
        """无 API Key 时的确定性响应，保证离线可跑通示例。"""
        # 识别用户想让哪个 skill 干活，从 system 里带出名称
        skill = ""
        for line in (system or "").splitlines():
            if line.startswith("SKILL:"):
                skill = line.split("SKILL:", 1)[1].strip()
                break
        topic = (user or "").strip()[:200]
        return _mock_reply(skill, topic)


def _mock_reply(skill: str, topic: str) -> str:
    """按 skill 返回结构化的离线占位结果（便于演示与测试）。"""
    cat = skill  # 兼容直接传 skill 名
    if "综述" in skill or "literature" in skill or "文献" in skill:
        return (
            f"# 文献综述（离线占位）\n\n"
            f"**主题**：{topic}\n\n"
            f"> 说明：当前为离线 Mock 模式，未调用真实大模型。配置 RESEARCH_LLM_PROVIDER=ollama 或 "
            f"设置 API Key 后，将输出真实文献调研与证据梳理。\n\n"
            f"## 检索方向\n1. 核心概念定义与边界\n2. 代表性工作与方法流派\n3. 争议点与证据缺口\n\n"
            f"## 待核验\n- 需回到原文核对引用与年份"
        )
    if "论文" in skill or "paper" in skill or "writing" in skill:
        return (
            f"# 论文写作（离线占位）\n\n"
            f"**选题**：{topic}\n\n"
            f"> 离线 Mock 模式。配置 LLM 后按 IMRaD 结构生成段落、引用与摘要。\n\n"
            f"## 拟定结构\n- 引言 / 相关工作 / 方法 / 结果 / 讨论 / 结论"
        )
    if "supervisor" in skill or "评审" in skill or "review" in skill:
        return (
            f"# 评审意见（离线占位）\n\n"
            f"**受评对象**：{topic}\n\n"
            f"> 离线 Mock 模式。配置 LLM 后输出缺陷诊断 / 可行性评估 / 风险提示。\n\n"
            f"## 风险提示\n- 数据与结论的因果链是否成立\n- 样本量与统计效力\n- 引用是否可回查"
        )
    return (
        f"# 科研产出（离线占位）\n\n"
        f"**主题**：{topic}\n\n"
        f"> 离线 Mock 模式，未调用真实大模型。"
    )