"""科研 Skill 集成模块（自包含，不依赖 app.*）。

把 GitHub 上多个高星科研 Skill 库（Imbad0202/academic-research-skills、
K-Dense-AI/scientific-agent-skills、Yuan1z0825/nature-skills、
fcakyon/phd-skills、Orchestra-Research/AI-research-SKILLs、
HKUSTDial/Supervisor-Skills）以「解析 SKILL.md 标准格式 → 本地注册表 →
调度层 → 执行器 → 评审后置」的方式集成进本项目。

设计原则：
- 不整仓 clone/硬拷贝外部源码，只解析 SKILL.md 提取
  触发条件 / 系统提示 / 输入参数 / 输出格式 / 约束规则。
- 科研任务产物统一输出到 ./output/research/，与情报输出 ./output/feed/ 隔离。
- 持久记忆：findings.md / research-log.md / research-state.yaml。
- 兼容本地 Ollama，无 API Key 时自动降级为离线确定性模式。
- 最小侵入：独立目录，不改动原有情报采集核心逻辑。
"""

__version__ = "0.1.0"

from research_skills.registry import Registry, get_registry  # noqa: E402,F401
from research_skills.scheduler import classify, dispatch  # noqa: E402,F401

__all__ = ["Registry", "get_registry", "classify", "dispatch"]