import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

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
)
from app.utils.security import hash_password


def _ensure_storage():
    os.makedirs(settings.PDF_DIR, exist_ok=True)


def _init_db():
    # 建表（SQLite/PostgreSQL 通用；轻量化默认 SQLite 单文件）
    Base.metadata.create_all(bind=engine)


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


app = FastAPI(title=settings.APP_NAME, version="0.1.0")

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
