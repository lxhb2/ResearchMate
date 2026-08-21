import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.models.user import User
from app.routers import (
    auth,
    papers,
    search,
    annotations,
    chat,
    conversations,
    projects,
    translate,
    term,
    settings as settings_router,
    agent_workflow,
    backup,
    agent,
    imports,
    graph,
    app_info,
    tasks,
)
from app.utils.security import hash_password
from app.services import task_queue


def _ensure_storage():
    os.makedirs(settings.PDF_DIR, exist_ok=True)


def _init_db():
    # 建表（SQLite/PostgreSQL 通用；轻量化默认 SQLite 单文件）
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite()
    from app.services import fts_service
    fts_service.ensure_fts()


def _migrate_sqlite() -> None:
    """轻量迁移：SQLite 下 create_all 不会给已有表追加新列，这里手动补齐。

    - papers.analysis_status：AI 分析进度。旧库中已存在的文献按旧流水线
      「ready 即分析完成」处理，默认补 'done'；新上传由模型默认 'pending'。
    - papers.summary：AI 全文总结缓存。
    - papers.last_page：上次阅读页码（长期记忆）。
    - paper_chunks.char_start/char_end：citation 溯源所需的原文字符偏移。
    （paper_chat_messages 是新表，create_all 会自动建，无需迁移。）
    """
    from sqlalchemy import text

    if not str(engine.url).startswith("sqlite"):
        return
    # papers 表：列名 -> 补列 DDL（NOT NULL 列需带 DEFAULT）
    paper_adds: dict[str, str] = {
        "analysis_status": "ALTER TABLE papers ADD COLUMN analysis_status "
        "VARCHAR(20) NOT NULL DEFAULT 'done'",
        "summary": "ALTER TABLE papers ADD COLUMN summary TEXT",
        "last_page": "ALTER TABLE papers ADD COLUMN last_page INTEGER",
    }
    # paper_chunks 表：列名 -> 补列 DDL
    chunk_adds: dict[str, str] = {
        "char_start": "ALTER TABLE paper_chunks ADD COLUMN char_start INTEGER",
        "char_end": "ALTER TABLE paper_chunks ADD COLUMN char_end INTEGER",
        "section": "ALTER TABLE paper_chunks ADD COLUMN section VARCHAR(160)",
        "meta": "ALTER TABLE paper_chunks ADD COLUMN meta TEXT",
    }
    try:
        with engine.begin() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(papers)"))]
            if cols:
                for col, ddl in paper_adds.items():
                    if col not in cols:
                        conn.execute(text(ddl))
                if "analysis_meta" not in cols:
                    conn.execute(text("ALTER TABLE papers ADD COLUMN analysis_meta TEXT"))
            chunk_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(paper_chunks)"))]
            if chunk_cols:
                for col, ddl in chunk_adds.items():
                    if col not in chunk_cols:
                        conn.execute(text(ddl))
            _migrate_doi_constraint(conn)
    except Exception:  # noqa: BLE001
        # 迁移失败不阻塞启动（新库首次建表时本就包含这些列）
        pass


def _migrate_doi_constraint(conn) -> None:
    """DOI 唯一约束按用户收敛：新增 (user_id, doi) 复合唯一索引。

    新库由 ORM 直接建复合唯一约束；旧库若遗留全局唯一索引，能删则删，
    SQLite 自动索引无法删除时保留（单用户本地应用下不影响使用）。
    """
    indexes = conn.execute(text("PRAGMA index_list('papers')")).fetchall()
    has_composite = any(str(row[1]) == "uq_papers_user_doi" for row in indexes)
    if not has_composite:
        try:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_papers_user_doi "
                    "ON papers(user_id, doi)"
                )
            )
        except Exception:  # noqa: BLE001
            pass
    for row in indexes:
        name = str(row[1])
        unique = bool(row[2])
        if not unique or name in ("uq_papers_user_doi",) or name.startswith("sqlite_autoindex"):
            continue
        try:
            cols = [str(c[2]) for c in conn.execute(text(f"PRAGMA index_info('{name}')")).fetchall()]
        except Exception:  # noqa: BLE001
            continue
        if cols == ["doi"]:
            try:
                conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
            except Exception:  # noqa: BLE001
                pass


def _ensure_default_user(db: Session) -> None:
    """Bootstrap the single default user so the frontend can auto-login."""
    if not settings.AUTO_LOGIN:
        return
    existing = db.query(User).filter(User.username == settings.AUTO_LOGIN_USERNAME).first()
    if existing:
        return
    user = User(
        username=settings.AUTO_LOGIN_USERNAME,
        password=hash_password(settings.AUTO_LOGIN_PASSWORD),
    )
    db.add(user)
    db.commit()


def _recover_stale_tasks() -> None:
    """把上次进程中断时遗留的 running 任务放回 pending，交给 worker 重试。"""
    try:
        from app.models.agent_task import AgentTask

        with SessionLocal() as db:
            db.query(AgentTask).filter(AgentTask.status == "running").update(
                {"status": "pending"}, synchronize_session=False
            )
            db.commit()
    except Exception:  # noqa: BLE001
        pass


def _recover_interrupted_papers() -> None:
    """启动时重放上次中断的论文任务（processing / analysis pending）。"""
    try:
        from app.models.paper import Paper
        from app.services import task_queue

        with SessionLocal() as db:
            stuck = (
                db.query(Paper)
                .filter(or_(Paper.status == "processing", Paper.analysis_status == "pending"))
                .order_by(Paper.created_at.asc())
                .all()
            )
            if not stuck:
                return
            print(f"[recovery] 发现 {len(stuck)} 篇未完成任务，开始后台重放")
            for paper in stuck:
                task_queue.enqueue(
                    db,
                    paper.user_id,
                    "paper_processing",
                    {"paper_id": str(paper.id)},
                )
    except Exception as e:  # noqa: BLE001
        print(f"[recovery] 启动恢复失败：{e}")


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

def _shutdown_pdf2zh() -> None:
    """退出时清理 pdf2zh 桥接进程，避免 PyInstaller 临时目录被占用。"""
    try:
        from app.services import pdf2zh_service

        pdf2zh_service.terminate_all()
    except Exception:  # noqa: BLE001
        pass


app.add_event_handler("shutdown", _shutdown_pdf2zh)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ensure_storage()
_init_db()
with SessionLocal() as db:
    _ensure_default_user(db)

_recover_stale_tasks()
task_queue.start_worker()

# 插件生态：启动时装载全部已启用插件（技能/工具/MCP 配置注册进对应注册表）
def _load_plugins() -> None:
    try:
        from app.agent.plugin_manager import get_plugin_manager

        result = get_plugin_manager().load_all()
        if result.get("failed"):
            print(f"[plugins] 装载失败：{result['failed']}")
    except Exception as e:  # noqa: BLE001
        print(f"[plugins] 启动装载异常：{e}")


_load_plugins()

prefix = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=prefix)
app.include_router(papers.router, prefix=prefix)
app.include_router(search.router, prefix=prefix)
app.include_router(annotations.router, prefix=prefix)
app.include_router(chat.router, prefix=prefix)
app.include_router(conversations.router, prefix=prefix)
app.include_router(projects.router, prefix=prefix)
app.include_router(translate.router, prefix=prefix)
app.include_router(term.router, prefix=prefix)
app.include_router(settings_router.router, prefix=prefix)
app.include_router(agent_workflow.router, prefix=prefix)
app.include_router(backup.router, prefix=prefix)
app.include_router(agent.router, prefix=prefix)
app.include_router(imports.router, prefix=prefix)
app.include_router(graph.router, prefix=prefix)
app.include_router(app_info.router, prefix=prefix)
app.include_router(tasks.router, prefix=prefix)

_recover_interrupted_papers()


def _resolve_frontend_dist() -> str:
    """解析前端静态目录。

    优先级：显式配置 FRONTEND_DIST > PyInstaller 内嵌解包目录（sys._MEIPASS/dist）。
    """
    if settings.FRONTEND_DIST:
        return settings.FRONTEND_DIST
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        cand = os.path.join(bundle, "dist")
        if os.path.isdir(cand):
            return cand
    return ""


@app.get("/")
def root():
    # 绿色包/生产模式：若已托管前端，则 / 直接返回前端首页
    dist = _resolve_frontend_dist()
    if dist and os.path.isdir(dist):
        index = os.path.join(dist, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
    return {"app": settings.APP_NAME, "status": "ok", "docs": "/docs"}


def _mount_frontend(app: FastAPI) -> None:
    """托管构建后的前端静态文件（单端口运行，供绿色便携包使用）。

    当存在可用的前端 dist 目录时启用。前端 baseURL 为 /api/v1，
    由后端自身处理；其余路径（含 SPA 前端路由）回退到 index.html。
    """
    dist = _resolve_frontend_dist()
    if not dist or not os.path.isdir(dist):
        return
    assets = os.path.join(dist, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # 静态文件优先；否则回退到 index.html 以支持前端路由
        if full_path:
            fp = os.path.join(dist, full_path)
            if os.path.isfile(fp):
                return FileResponse(fp)
        index = os.path.join(dist, "index.html")
        return FileResponse(index)


# 挂载前端静态资源（在后端 API 路由之后，避免拦截 /api）
_mount_frontend(app)
