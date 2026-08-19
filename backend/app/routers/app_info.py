"""应用信息与 GitHub Releases 版本检查。"""
import re

import requests
from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/app", tags=["app"])


def _parse_version(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in parts[:3]) or (0, 0, 0)


@router.get("/info")
def app_info():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "repo": settings.GITHUB_REPO,
        "update_url": f"https://github.com/{settings.GITHUB_REPO}/releases/latest",
    }


@router.get("/update/check")
def check_update():
    """查询 GitHub Releases 最新版本，返回可供前端展示的更新信息。"""
    api_url = f"https://api.github.com/repos/{settings.GITHUB_REPO}/releases/latest"
    try:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ResearchMate"}
        try:
            resp = requests.get(api_url, timeout=12, headers=headers)
        except requests.exceptions.SSLError:
            # 本地/企业网络证书链不全时，退回到不校验证书的 GitHub 公共接口
            import urllib3  # noqa: PLC0415

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(api_url, timeout=12, headers=headers, verify=False)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc),
            "current": settings.APP_VERSION,
            "latest": None,
            "release_url": f"https://github.com/{settings.GITHUB_REPO}/releases/latest",
            "assets": [],
        }

    latest = data.get("tag_name") or data.get("name") or ""
    assets = [
        {
            "name": a.get("name"),
            "url": a.get("browser_download_url"),
            "size": a.get("size"),
        }
        for a in (data.get("assets") or [])
        if a.get("browser_download_url")
    ]
    current = settings.APP_VERSION
    has_update = _parse_version(latest) > _parse_version(current) if latest else False
    return {
        "ok": True,
        "current": current,
        "latest": latest,
        "has_update": has_update,
        "release_url": data.get("html_url") or f"https://github.com/{settings.GITHUB_REPO}/releases/latest",
        "release_name": data.get("name"),
        "published_at": data.get("published_at"),
        "assets": assets,
    }
