"""默认固定工作流模板。

提供开箱即用的固定工作流，覆盖科研全流程：

- 科研新手全流程（tpl_beginner_flow，默认/主模板）：
  针对科研小白的一次完整研究+论文撰写引导，按标准研究流程分 6 个阶段推进，
  每阶段带新手讲解（guide）与人工确认关卡（confirm），可暂停、学习、继续，
  适配「选题→文献调研→研究设计→数据分析→论文写作→引用导出」的能力迭代路径。
- 新文献入库流：解析 -> 总结 -> 关联检索 -> 写入笔记
- 综述对比流：列出文库 -> 检索素材 -> 多篇对比 -> 写入项目
- 实验辅助流：实验设计建议 -> 检索实验设置 -> 数据分析 -> 写入笔记

这些模板可由用户直接运行，也可作为 Agent 生成工作流的参考蓝本。
后续将在此基础上迭代「高级自定义工作流」（白板式拖拽）与机器学习能力。
"""
from app.agent.schema import Workflow
from app.agent.tools import get_tool

# 模板原始定义（dict，交由 Workflow 模型校验）
TEMPLATES_RAW: list[dict] = [
    {
        "workflow_id": "tpl_beginner_flow",
        "name": "科研新手全流程（引导式）",
        "description": (
            "面向科研小白的完整研究+论文撰写引导：按标准研究流程分阶段推进，"
            "每阶段附新手讲解与人工确认关卡，支持暂停学习、确认后继续。"
            "运行前请准备：user_vars.topic（研究主题）、user_vars.question（分析需求）、"
            "user_vars.data（实验数据，可选）。"
        ),
        "start": "c1",
        "output": "t8",
        "nodes": {
            # ---- 阶段一：选题与定题 ----
            "c1": {
                "id": "c1", "type": "confirm", "stage": "一、选题与定题",
                "description": "选题指导（请阅读左侧引导后确认开始）",
                "guide": "选题三原则：①「小而精」——首篇论文忌大而空；②在导师/课题组射程内，最易获得指导与数据；"
                         "③从顶刊论文的 Discussion/Conclusion 里找「研究缺口」（Future work）。"
                         "建议结合导师课题，用 1-2 句话写出你的研究问题。",
                "next": "t1",
            },
            "t1": {
                "id": "t1", "type": "tool", "tool": "paper_summarize", "stage": "一、选题与定题",
                "description": "精读最新导入的一篇文献，找切入点",
                "args": {"source": "latest", "mode": "full"}, "next": "c2",
            },
            "c2": {
                "id": "c2", "type": "confirm", "stage": "一、选题与定题",
                "description": "确认选题",
                "guide": "请在运行参数 user_vars.topic 中填写你的研究主题。好的问题=成功一半，"
                         "先将 Topic 收敛为可回答的 Problem（研究问题）。",
                "next": "t2",
            },
            # ---- 阶段二：文献调研 ----
            "t2": {
                "id": "t2", "type": "tool", "tool": "rag_search", "stage": "二、文献调研",
                "description": "按主题语义检索相关文献",
                "args": {"query": "$user.topic", "top_k": 5, "dimension": "method"}, "next": "t3",
            },
            "t3": {
                "id": "t3", "type": "tool", "tool": "llm_compare", "stage": "二、文献调研",
                "description": "提炼核心文献的方法/结论对比",
                "args": {"query": "$user.topic", "dimensions": ["method", "results", "contributions"]}, "next": "c3",
            },
            "c3": {
                "id": "c3", "type": "confirm", "stage": "二、文献调研",
                "description": "确认核心文献",
                "guide": "文献阅读两步走：先「泛览」30-50 篇（看标题/摘要/结论/图表，画知识地图）；再「精读」10-15 篇"
                         "高相关文献，用表格梳理每篇的「研究问题、方法、结论、不足」，据此定位空白、收敛选题。",
                "next": "t4",
            },
            # ---- 阶段三：研究问题与实验设计 ----
            "t4": {
                "id": "t4", "type": "tool", "tool": "experiment_plan", "stage": "三、研究设计",
                "description": "生成研究假设与实验设计建议",
                "args": {"question": "$user.topic", "top_k": 4}, "next": "c4",
            },
            "c4": {
                "id": "c4", "type": "confirm", "stage": "三、研究设计",
                "description": "确认研究假设与设计",
                "guide": "在动笔前明确：研究假设、基线选择、数据集、评估指标。设计要「周全」——对比实验不可或缺，"
                         "数据尽量大众公开。必要时先与导师/师兄姐对齐再进入下一步。",
                "next": "t5",
            },
            # ---- 阶段四：数据分析 ----
            "t5": {
                "id": "t5", "type": "tool", "tool": "rag_search", "stage": "四、数据分析",
                "description": "检索相关文献的实验设置作参考",
                "args": {"query": "$user.topic", "top_k": 3, "dimension": "method"}, "next": "t6",
            },
            "t6": {
                "id": "t6", "type": "tool", "tool": "data_analyze", "stage": "四、数据分析",
                "description": "对实验数据做统计分析",
                "args": {"question": "$user.question", "data": "$user.data", "exec_code": True}, "next": "c5",
            },
            "c5": {
                "id": "c5", "type": "confirm", "stage": "四、数据分析",
                "description": "确认统计结果与图表",
                "guide": "检查统计结果是否显著、图表是否支撑结论。数据质量是论文的基石：每一组数据都必须真实、可信，"
                         "并与你论文中的论点严丝合缝对应。",
                "next": "t7",
            },
            # ---- 阶段五：论文骨架与倒序写作 ----
            "t7": {
                "id": "t7", "type": "tool", "tool": "note_append", "stage": "五、论文写作",
                "description": "生成论文大纲与写作顺序指南并写入写作项目",
                "args": {"project_id": "auto",
                         "content": "## 论文大纲（{ $user.topic }）\n\n"
                                    "1. 标题：研究对象+方法+核心发现\n"
                                    "2. 摘要：微缩论文（背景/目的/方法/关键结果/结论）\n"
                                    "3. 引言：沙漏结构（宽背景→文献收窄→研究空白→研究问题）\n"
                                    "4. 文献综述：系统梳理前人工作\n"
                                    "5. 研究方法：数据来源/实验设计/分析工具，保证可复现\n"
                                    "6. 研究结果：客观呈现，善用图表\n"
                                    "7. 讨论：结果含义，与既有文献对话，阐明贡献与局限\n"
                                    "8. 结论：总结核心发现，重申价值，提出展望\n"
                                    "9. 参考文献：严格遵循目标期刊格式\n\n"
                                    "## 倒序写作建议\n"
                                    "先写「研究方法」和「研究结果」（最容易），再写「讨论」和「引言」，最后写「摘要」和「结论」。"
                                    "先完成，再完美。分模块每天一个小目标。",
                         },
                "next": "c6",
            },
            "c6": {
                "id": "c6", "type": "confirm", "stage": "五、论文写作",
                "description": "确认大纲与写作顺序",
                "guide": "写作技巧：①倒序写作减轻压力（方法/结果→讨论/引言→摘要/结论）；②番茄工作法25分钟纯写作，"
                         "不回看修改，遇到要查证的先标[待查]；③每段「观点-论据-小结」结构。",
                "next": "t8",
            },
            # ---- 阶段六：引用与导出 ----
            "t8": {
                "id": "t8", "type": "tool", "tool": "citation_generate", "stage": "六、引用与导出",
                "description": "生成参考文献引用格式",
                "args": {"query": "$user.topic", "format": "GB7714"}, "next": "e",
            },
            "e": {"id": "e", "type": "end"},
        },
    },
    {
        "workflow_id": "tpl_paper_ingest",
        "name": "新文献入库流",
        "description": "解析最新导入的 PDF 文献，自动总结核心贡献，检索相关文献并写入最近的写作项目。",
        "start": "n1",
        "output": "n5",
        "nodes": {
            "n1": {
                "id": "n1", "type": "tool", "tool": "paper_parse", "retry": 1,
                "description": "解析最新导入的 PDF 文献",
                "args": {"source": "latest"}, "next": "n2",
            },
            "n2": {
                "id": "n2", "type": "condition",
                "description": "判断文献是否解析成功",
                "condition": {"variable": "results.n1.found", "operator": "==", "value": True},
                "next_if_true": "n3", "next_if_false": "n6",
            },
            "n3": {
                "id": "n3", "type": "tool", "tool": "paper_summarize", "retry": 1,
                "description": "对解析出的文献做全文结构化总结",
                "args": {"source": "$results.n1.paper_id", "mode": "full"}, "next": "n4",
            },
            "n4": {
                "id": "n4", "type": "tool", "tool": "rag_search",
                "description": "按文献主题检索相关片段",
                "args": {"query": "$results.n1.title", "top_k": 3, "dimension": "method"}, "next": "n5",
            },
            "n5": {
                "id": "n5", "type": "tool", "tool": "note_append",
                "description": "将总结与相关文献写入最近的写作项目",
                "args": {"project_id": "auto",
                         "content": "## 文献总结\n$results.n3.summary\n\n## 相关文献\n$results.n4.hits"},
                "next": "n6",
            },
            "n6": {"id": "n6", "type": "end"},
        },
    },
    {
        "workflow_id": "tpl_literature_review",
        "name": "综述对比流",
        "description": "针对一个研究主题，从文库检索素材进行多篇对比，生成对比表格并写入写作项目。",
        "start": "n1",
        "output": "n4",
        "nodes": {
            "n1": {
                "id": "n1", "type": "tool", "tool": "library_list",
                "description": "列出当前文库概况",
                "args": {"limit": 20}, "next": "n2",
            },
            "n2": {
                "id": "n2", "type": "tool", "tool": "rag_search",
                "description": "按研究主题检索方法片段",
                "args": {"query": "$user.topic", "top_k": 5, "dimension": "method"}, "next": "n3",
            },
            "n3": {
                "id": "n3", "type": "tool", "tool": "llm_compare", "retry": 1,
                "description": "对检索到的文献生成对比表",
                "args": {"query": "$user.topic", "dimensions": ["method", "results", "contributions"]},
                "next": "n4",
            },
            "n4": {
                "id": "n4", "type": "tool", "tool": "note_append",
                "description": "将对比表写入写作项目",
                "args": {"project_id": "auto", "content": "## 文献综述对比\n$results.n3.table"}, "next": "n5",
            },
            "n5": {"id": "n5", "type": "end"},
        },
    },
    {
        "workflow_id": "tpl_experiment_help",
        "name": "实验辅助流",
        "description": "根据研究问题生成实验设计建议，检索相关实验设置，并对传入数据做统计分析。",
        "start": "n1",
        "output": "n4",
        "nodes": {
            "n1": {
                "id": "n1", "type": "tool", "tool": "experiment_plan",
                "description": "生成实验设计建议",
                "args": {"question": "$user.topic", "top_k": 4}, "next": "n2",
            },
            "n2": {
                "id": "n2", "type": "tool", "tool": "rag_search",
                "description": "检索相关文献的实验设置",
                "args": {"query": "$user.topic", "top_k": 4, "dimension": "method"}, "next": "n3",
            },
            "n3": {
                "id": "n3", "type": "tool", "tool": "data_analyze", "retry": 1,
                "description": "对实验数据做统计分析",
                "args": {"question": "$user.question", "data": "$user.data", "exec_code": True}, "next": "n4",
            },
            "n4": {
                "id": "n4", "type": "tool", "tool": "note_append",
                "description": "将分析结果写入写作项目",
                "args": {"project_id": "auto",
                         "content": "## 实验设计建议\n$results.n1.plan\n\n## 数据分析结果\n$results.n3.result"},
                "next": "n5",
            },
            "n5": {"id": "n5", "type": "end"},
        },
    },
]


class Template:
    """单个工作流模板（已通过 Workflow 模型校验）。"""

    def __init__(self, raw: dict):
        try:
            self.workflow = Workflow.model_validate(raw)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"模板 {raw.get('workflow_id', '?')} 校验失败: {e}") from e

    def to_public(self) -> dict:
        wf = self.workflow
        return {
            "workflow_id": wf.workflow_id,
            "name": wf.name,
            "description": wf.description,
            "start": wf.start,
            "nodes": wf.model_dump()["nodes"],
            "output": wf.output,
        }


def build_templates() -> list[Template]:
    return [Template(raw) for raw in TEMPLATES_RAW]


def template_ids() -> list[str]:
    return [t.workflow.workflow_id for t in build_templates()]


def get_template(workflow_id: str):
    for t in build_templates():
        if t.workflow_id == workflow_id:
            return t
    return None