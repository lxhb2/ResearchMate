"""Database engine, session, and base model setup.

轻量化本地存储：默认使用 SQLite 单文件（零服务、零配置、内存占用极小）。
兼容 PostgreSQL（若用户显式配置 DATABASE_URL 指向 postgres）。
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import NullPool

from app.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    # SQLite 单文件：NullPool 避免多连接写锁；显式处理线程检查
    poolclass=NullPool if _is_sqlite else None,
    # 提高 sqlite 写锁等待超时（默认 5s），避免后台处理论文时用户并发写失败
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)


if _is_sqlite:
    # WAL 模式：读不阻塞写、写不阻塞读，显著降低"database is locked"概率
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()