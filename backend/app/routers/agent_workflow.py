"""Agent 工作流 HTTP 接口。

接口：
- POST /agent/generate-workflow : 输入自然语言指令，生成工作流 JSON
- POST /workflow/run           : 提交工作流 JSON，执行并返回结果
- GET  /workflow/{run_id}      : 查询某次运行状态
"""
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.agent import Agent, WorkflowGenerationError
from app.agent.executor import Executor
from app.agent.llm_adapter import LLMAdapter
from app.agent.schema import Workflow
from app.agent.tools import ToolContext
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.workflow_run import WorkflowRun
from app.models.workflow_template import WorkflowTemplate
from app.services import settings_service

router = APIRouter(tags=["agent-workflow"])


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------

class GenerateWorkflowRequest(BaseModel):
    user_prompt: str = Field(..., description="用户自然语言科研指令")


class GenerateWorkflowResponse(BaseModel):
    workflow_json: dict
    description: str = Field(..., description="任务拆解说明")


class WorkflowRunRequest(BaseModel):
    workflow_json: dict = Field(..., description="Agent 生成的工作流 JSON")
    user_vars: dict[str, Any] = Field(default_factory=dict, description="运行期用户输入（模板参数，如 topic/question/data）")


class WorkflowRunResponse(BaseModel):
    run_id: str
    workflow_id: str = ""
    status: str
    logs: list[Any] = []
    results: dict[str, Any] = {}
    final_output: Any = None
    error: str | None = None
    pending_confirm_nodes: list[str] = []


class TemplateListItem(BaseModel):
    id: str = ""                      # 自定义模板的数据库 id（固定模板为空）
    workflow_id: str
    name: str
    description: str
    source: Literal["fixed", "custom"] = "fixed"   # fixed=内建固定模板；custom=我的自定义模板
    editable: bool = False            # 是否可删除/编辑（仅自定义模板为 True）
    start: str
    nodes: dict[str, Any] = {}
    output: str | None = None


class WorkflowRunDetail(BaseModel):
    run_id: str
    workflow_id: str = ""
    status: str
    workflow_json: dict = {}
    logs: list[Any] = []
    results: dict[str, Any] = {}
    final_output: Any = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""


class SaveTemplateRequest(BaseModel):
    name: str = Field(..., description="模板名称")
    description: str = Field(default="", description="模板说明")
    workflow_json: dict = Field(..., description="完整工作流定义（Workflow 可校验）")


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _build_llm(db: Session, user_id) -> LLMAdapter:
    """根据用户设置构建 LLM 适配器（LiteLLM 兼容层）。"""
    cfg = settings_service.get_llm_config(db, str(user_id))
    return LLMAdapter.from_config(cfg)


def _safe_jsonable(obj: Any) -> Any:
    """把可能含 UUID 等非 JSON 类型的对象转为可序列化结构。"""
    import uuid as _uuid
    if isinstance(obj, _uuid.UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _safe_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_jsonable(v) for v in obj]
    return obj


def _hexid() -> str:
    import uuid as _uuid
    return _uuid.uuid4().hex


# ---------------------------------------------------------------------------
# 接口实现
# ---------------------------------------------------------------------------

@router.get("/workflow/templates", response_model=list[TemplateListItem])
def list_templates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出所有可运行模板：内建固定工作流 + 我的自定义模板。

    自定义模板由「自然语言生成 / 白板式拖拽」创建后保存而来，与固定模板
    一样可被选中进入对话式执行。
    """
    from app.agent import templates as tpl_mod
    items: list[TemplateListItem] = [
        TemplateListItem(
            workflow_id=t.workflow.workflow_id,
            name=t.workflow.name,
            description=t.workflow.description,
            source="fixed",
            editable=False,
            start=t.workflow.start,
            nodes=t.to_public()["nodes"],
            output=t.workflow.output,
        )
        for t in tpl_mod.build_templates()
    ]
    # 我的自定义模板
    customs = (
        db.query(WorkflowTemplate)
        .filter(WorkflowTemplate.user_id == user.id)
        .order_by(WorkflowTemplate.created_at.desc())
        .all()
    )
    for ct in customs:
        wf = (ct.workflow_json or {})
        items.append(TemplateListItem(
            id=str(ct.id),
            workflow_id=ct.workflow_id or str(ct.id),
            name=ct.name,
            description=ct.description,
            source="custom",
            editable=True,
            start=wf.get("start", ""),
            nodes=(wf.get("nodes") or {}),
            output=wf.get("output"),
        ))
    return items


@router.post("/workflow/templates", response_model=TemplateListItem)
def save_template(
    body: SaveTemplateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把工作流保存为「我的自定义模板」，供下次直接选中运行。"""
    name = body.name.strip() or "未命名模板"
    try:
        workflow = Workflow.model_validate(body.workflow_json)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"非法的工作流结构: {e}")

    ct = WorkflowTemplate(
        user_id=user.id,
        name=name,
        description=body.description.strip(),
        workflow_id=workflow.workflow_id or _hexid(),
        workflow_json=_safe_jsonable(workflow.model_dump()),
    )
    db.add(ct)
    db.commit()
    db.refresh(ct)
    wf = ct.workflow_json or {}
    return TemplateListItem(
        id=str(ct.id),
        workflow_id=ct.workflow_id,
        name=ct.name,
        description=ct.description,
        source="custom",
        editable=True,
        start=wf.get("start", ""),
        nodes=(wf.get("nodes") or {}),
        output=wf.get("output"),
    )


@router.delete("/workflow/templates/{template_id}")
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除一个自定义模板（仅限本人）。"""
    from uuid import UUID
    try:
        uid = UUID(template_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="非法的 template_id")
    ct = db.get(WorkflowTemplate, str(uid))
    if not ct or str(ct.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(ct)
    db.commit()
    return {"ok": True}


@router.get("/agent/tools")
def list_tools(user: User = Depends(get_current_user)):
    """工具迭代接口：列出当前可用工具及其参数 Schema（供前端/Agent 使用）。"""
    from app.agent import tools as tools_mod
    return {"tools": tools_mod.tool_catalog()}


@router.get("/agent/dimensions")
def list_dimensions(user: User = Depends(get_current_user)):
    """6 维度向量表元数据接口：列出全部语义维度及其中文名。

    这是工作流调用「6 维度向量表」的统一schema入口，供前端渲染维度选择、
    Agent 生成维度感知工作流使用；维度名与 paper_service 拆分及
    search_service.semantic_search 的 dimension 参数保持一致。
    """
    from app.services.search_service import DIMENSIONS, DIMENSION_LABELS
    return {
        "dimensions": [
            {"key": d, "label": DIMENSION_LABELS.get(d, d)} for d in DIMENSIONS
        ]
    }


@router.post("/agent/generate-workflow", response_model=GenerateWorkflowResponse)
def generate_workflow(
    body: GenerateWorkflowRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """输入科研指令，由 Agent 生成工作流 JSON。"""
    prompt = body.user_prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="user_prompt 不能为空")
    llm = _build_llm(db, user.id)
    agent = Agent(llm)
    try:
        workflow, description = agent.generate_workflow(prompt)
    except WorkflowGenerationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return GenerateWorkflowResponse(
        workflow_json=workflow.model_dump(),
        description=description,
    )


@router.post("/workflow/run", response_model=WorkflowRunResponse)
def run_workflow(
    body: WorkflowRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """校验并执行工作流，返回执行结果。"""
    # 强校验工作流结构
    try:
        workflow = Workflow.model_validate(body.workflow_json)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"非法的工作流结构: {e}")

    llm = _build_llm(db, user.id)
    ctx = ToolContext(db=db, user_id=user.id, llm=llm, mock=False)
    executor = Executor(llm=llm, auto_confirm=False)

    # 先落一条 running 记录
    run = WorkflowRun(
        user_id=user.id,
        workflow_id=workflow.workflow_id,
        status="running",
        workflow_json=_safe_jsonable(workflow.model_dump()),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    result = executor.run(workflow, ctx, run_id=str(run.id), user_vars=body.user_vars)

    # 更新记录
    run.status = result.status
    run.logs = _safe_jsonable([l.model_dump() for l in result.logs])
    run.results = _safe_jsonable(result.results)
    run.final_output = _safe_jsonable(result.final_output)
    run.error = result.error
    if result.status == "awaiting_confirm":
        # 保存可恢复的执行状态与暂停关卡
        run.state_json = _safe_jsonable(result.state)
        run.current_node = result.current_node
    db.commit()

    return WorkflowRunResponse(
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        status=result.status,
        logs=run.logs,
        results=run.results,
        final_output=run.final_output,
        error=run.error,
        pending_confirm_nodes=result.pending_confirm_nodes,
    )


@router.post("/workflow/resume/{run_id}", response_model=WorkflowRunResponse)
def resume_workflow(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从暂停点恢复执行（科研新手引导工作流的「继续」关卡）。

    用户确认某一阶段关卡后，从保存的暂停节点继续，前序节点结果保留。
    """
    from uuid import UUID
    try:
        uid = UUID(run_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="非法的 run_id")
    run = db.get(WorkflowRun, str(uid))
    if not run or str(run.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.status != "awaiting_confirm" or not run.current_node:
        raise HTTPException(status_code=400, detail="该运行未处于待恢复状态")

    # 仅允许恢复「确认」关卡
    wf_nodes = (run.workflow_json or {}).get("nodes", {})
    node = wf_nodes.get(run.current_node)
    if not node or node.get("type") != "confirm":
        raise HTTPException(status_code=400, detail="暂停点不是人工确认节点，无法恢复")

    try:
        workflow = Workflow.model_validate(run.workflow_json)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"非法的工作流结构: {e}")

    llm = _build_llm(db, user.id)
    ctx = ToolContext(db=db, user_id=user.id, llm=llm, mock=False)
    executor = Executor(llm=llm, auto_confirm=False)

    run.status = "running"
    db.commit()
    result = executor.run(
        workflow, ctx,
        run_id=str(run.id),
        user_vars=(run.state_json or {}).get("user", {}),
        initial_state=run.state_json or {},
        start_node=run.current_node,
        resume_node=run.current_node,
    )

    run.status = result.status
    run.logs = _safe_jsonable([l.model_dump() for l in result.logs])
    run.results = _safe_jsonable(result.results)
    run.final_output = _safe_jsonable(result.final_output)
    run.error = result.error
    if result.status == "awaiting_confirm":
        run.state_json = _safe_jsonable(result.state)
        run.current_node = result.current_node
    else:
        run.state_json = None
        run.current_node = None
    db.commit()

    return WorkflowRunResponse(
        run_id=str(run.id),
        workflow_id=result.workflow_id,
        status=result.status,
        logs=run.logs,
        results=run.results,
        final_output=run.final_output,
        error=run.error,
        pending_confirm_nodes=result.pending_confirm_nodes,
    )


@router.get("/workflow/{run_id}", response_model=WorkflowRunDetail)
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """查询某次工作流运行状态。"""
    from uuid import UUID
    try:
        uid = UUID(run_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="非法的 run_id")
    run = db.get(WorkflowRun, str(uid))
    if not run or str(run.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return WorkflowRunDetail(
        run_id=str(run.id),
        workflow_id=run.workflow_id,
        status=run.status,
        workflow_json=run.workflow_json or {},
        logs=run.logs or [],
        results=run.results or {},
        final_output=run.final_output,
        error=run.error,
        created_at=run.created_at.isoformat() if run.created_at else "",
        updated_at=run.updated_at.isoformat() if run.updated_at else "",
    )