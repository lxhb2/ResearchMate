"""模块路径与运行配置。

科研 Skill 模块自包含，路径基于本文件推导，避免依赖 app.* 的全局配置，
保证「最小侵入」：把本目录拷到任意 Python 项目即可独立运行。
"""
import os

# 模块根目录（本文件所在目录）
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# 内置 SKILL.md 模板目录
TEMPLATES_DIR = os.environ.get("RESEARCH_SKILL_TEMPLATES_DIR", os.path.join(MODULE_DIR, "templates"))

# 注册表文件（相对模块根 / 可由环境变量覆盖）
REGISTRY_PATH = os.environ.get(
    "RESEARCH_SKILL_REGISTRY", os.path.join(MODULE_DIR, "skills_registry.json")
)


def _default_output_dir() -> str:
    """科研产物根目录 ./output/，其下 research/ 与 feed/ 隔离。"""
    base = os.environ.get("RESEARCH_OUTPUT_DIR", os.path.join(os.getcwd(), "output"))
    return os.path.join(base, "research")


# 科研产物输出目录
RESEARCH_OUTPUT_DIR = os.environ.get("RESEARCH_SKILL_OUTPUT_DIR", _default_output_dir())

# 持久记忆文件名（复用 Orchestra-Research 的设计）
STATE_FILE = "research-state.yaml"
LOG_FILE = "research-log.md"
FINDINGS_FILE = "findings.md"


def ensure_dirs() -> None:
    """确保产物目录存在。"""
    os.makedirs(RESEARCH_OUTPUT_DIR, exist_ok=True)


# ---- LLM 提供方配置（支持 Ollama / OpenAI 兼容 / 离线 Mock）----
LLM_PROVIDER = os.environ.get("RESEARCH_LLM_PROVIDER", "").strip().lower()  # ollama|openai|mock|auto
OLLAMA_BASE_URL = os.environ.get("RESEARCH_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("RESEARCH_OLLAMA_MODEL", "llama3")
OPENAI_API_KEY = os.environ.get("RESEARCH_OPENAI_API_KEY", os.environ.get("LLM_API_KEY", ""))
OPENAI_BASE_URL = os.environ.get("RESEARCH_OPENAI_BASE_URL", os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"))
OPENAI_MODEL = os.environ.get("RESEARCH_OPENAI_MODEL", os.environ.get("LLM_MODEL", "gpt-4o"))