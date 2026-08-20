"""本地数据备份 / 恢复接口。

轻量化说明：项目数据全部本地保存（SQLite 单文件 + storage/pdfs 目录）。
备份 = 把数据库文件与 PDF 目录打包为一个 zip；恢复 = 上传 zip 覆盖。
这样用户无需云盘即可随时备份个人数据到本地。
"""
import io
import os
import shutil
import tempfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/backup", tags=["backup"])


def _sqlite_db_path() -> str:
    """解析 SQLite 数据库文件路径（sqlite:///...）。"""
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return ""


def _safe_copy_sqlite() -> bytes:
    """用 SQLite 在线备份 API 生成数据库文件字节（避免并发写锁）。"""
    path = _sqlite_db_path()
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=500, detail="当前不是 SQLite 数据库，无法备份")
    import sqlite3
    src = sqlite3.connect(path)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        dest = sqlite3.connect(tmp_path)
        try:
            with dest:
                src.backup(dest)
        finally:
            dest.close()
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        src.close()
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.get("/export")
def export_backup(user: User = Depends(get_current_user)):
    """导出全部本地数据为一个 zip（数据库 + PDF 文件）。"""
    try:
        db_bytes = _safe_copy_sqlite()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"备份数据库失败: {e}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("researchmate.db", db_bytes)
        pdf_dir = settings.PDF_DIR
        if os.path.isdir(pdf_dir):
            for root, _dirs, files in os.walk(pdf_dir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    rel = os.path.join("pdfs", fn)
                    zf.write(fp, rel)
        agent_dir = os.path.join(settings.STORAGE_DIR, "agent")
        if os.path.isdir(agent_dir):
            for root, _dirs, files in os.walk(agent_dir):
                for fn in files:
                    fp = os.path.join(root, fn)
                    rel = os.path.join("agent", os.path.relpath(fp, agent_dir))
                    zf.write(fp, rel)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=researchmate-backup.zip"},
    )


@router.post("/restore")
def restore_backup(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """从备份 zip 恢复数据（覆盖现有数据库与 PDF 目录）。

    注意：恢复会覆盖当前所有数据，请先自行确认。
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 备份文件")

    data = file.file.read()
    tmpdir = tempfile.mkdtemp(prefix="researchmate_restore_")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # 防御 Zip Slip：逐成员校验提取目标必须在 tmpdir 内
            tmpdir_norm = os.path.normpath(tmpdir)
            for member in zf.infolist():
                target = os.path.normpath(os.path.join(tmpdir_norm, member.filename))
                if not target.startswith(tmpdir_norm + os.sep):
                    raise HTTPException(status_code=400, detail=f"备份包包含非法路径: {member.filename}")
                zf.extract(member, tmpdir)

        # 恢复数据库
        db_path = _sqlite_db_path()
        if not db_path:
            raise HTTPException(status_code=500, detail="当前不是 SQLite 数据库，无法恢复")
        src_db = os.path.join(tmpdir, "researchmate.db")
        if not os.path.exists(src_db):
            raise HTTPException(status_code=400, detail="备份包中缺少 researchmate.db")
        # 先备份现有库，恢复失败可回退
        backup_current = None
        if os.path.exists(db_path):
            backup_current = db_path + ".bak"
            shutil.copy2(db_path, backup_current)
        try:
            shutil.copy2(src_db, db_path)
            # 清理可能残留的 WAL/SHM 文件，避免旧事务被回放覆盖刚恢复的数据
            for suffix in ("-wal", "-shm"):
                stray = db_path + suffix
                if os.path.exists(stray):
                    try:
                        os.remove(stray)
                    except OSError:
                        pass
        except Exception as e:  # noqa: BLE001
            if backup_current and os.path.exists(backup_current):
                shutil.copy2(backup_current, db_path)
            raise HTTPException(status_code=500, detail=f"恢复数据库失败: {e}")

        # 恢复 PDF 目录
        pdf_dir = settings.PDF_DIR
        os.makedirs(pdf_dir, exist_ok=True)
        src_pdfs = os.path.join(tmpdir, "pdfs")
        if os.path.isdir(src_pdfs):
            for fn in os.listdir(src_pdfs):
                fp = os.path.join(src_pdfs, fn)
                if os.path.isfile(fp):
                    shutil.copy2(fp, os.path.join(pdf_dir, fn))

        # 恢复 Agent 数据（技能 / 插件 / MCP 配置 / 长期记忆），需重启后完全生效
        src_agent = os.path.join(tmpdir, "agent")
        if os.path.isdir(src_agent):
            storage_abs = os.path.abspath(settings.STORAGE_DIR)
            agent_abs = os.path.abspath(os.path.join(settings.STORAGE_DIR, "agent"))
            if agent_abs != storage_abs and not agent_abs.startswith(storage_abs + os.sep):
                raise HTTPException(status_code=500, detail="存储目录配置异常，无法恢复 Agent 数据")
            os.makedirs(settings.STORAGE_DIR, exist_ok=True)
            try:
                if os.path.isdir(agent_abs):
                    shutil.rmtree(agent_abs)
                shutil.copytree(src_agent, agent_abs)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"恢复 Agent 数据失败: {e}") from e

        # 清理临时备份
        if backup_current and os.path.exists(backup_current):
            try:
                os.remove(backup_current)
            except OSError:
                pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"ok": True, "message": "恢复成功，请刷新页面；若恢复了 Agent 数据，建议重启应用。"}
