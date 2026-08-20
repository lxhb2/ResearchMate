"""个人术语表：本地 JSON 存储，复用翻译/术语解释结果。"""
import json
import os
import time
import uuid

from app.config import settings as app_settings


def _path() -> str:
    d = os.path.join(app_settings.STORAGE_DIR, "agent")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "glossary.json")


def _load() -> dict[str, list[dict]]:
    p = _path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, list[dict]]) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_terms(user_id: str) -> list[dict]:
    return _load().get(str(user_id), [])


def search_terms(user_id: str, query: str, limit: int = 10) -> list[dict]:
    q = (query or "").strip().lower()
    terms = list_terms(user_id)
    if not q:
        return terms[:limit]
    hits = []
    for t in terms:
        hay = f"{t.get('term','')} {t.get('definition','')} {t.get('translation','')}".lower()
        if q in hay:
            hits.append(t)
    return hits[:limit]


def add_term(
    user_id: str,
    term: str,
    definition: str = "",
    translation: str = "",
    source_lang: str = "",
    target_lang: str = "",
) -> dict:
    term = (term or "").strip()
    if not term:
        raise ValueError("术语不能为空")
    data = _load()
    uid = str(user_id)
    items = data.setdefault(uid, [])
    item = {
        "id": uuid.uuid4().hex,
        "term": term,
        "definition": (definition or "").strip(),
        "translation": (translation or "").strip(),
        "source_lang": source_lang,
        "target_lang": target_lang,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # 同术语去重：更新已有条目
    for i, old in enumerate(items):
        if old.get("term", "").lower() == term.lower():
            items[i] = item
            _save(data)
            return item
    items.append(item)
    _save(data)
    return item


def delete_term(user_id: str, term_id: str) -> bool:
    data = _load()
    items = data.get(str(user_id), [])
    rest = [t for t in items if t.get("id") != term_id]
    if len(rest) == len(items):
        return False
    data[str(user_id)] = rest
    _save(data)
    return True
