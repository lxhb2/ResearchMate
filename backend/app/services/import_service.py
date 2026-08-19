"""文献导入服务：Zotero 库 / BibTeX / RIS 解析与 Paper 映射。

单机场景：用户提供 Zotero 数据目录（含 zotero.sqlite 与 storage/），
本服务以只读方式解析元数据与附件，映射为 ResearchMate 的 Paper 结构。
BibTeX / RIS 为自包含的轻量解析器，不额外引入第三方依赖。
"""
import os
import re
import sqlite3
from typing import Optional


# ---------------------------------------------------------------------------
# Zotero 解析
# ---------------------------------------------------------------------------
ZOTERO_ITEM_TYPES = {
    "journalArticle", "book", "bookSection", "conferencePaper", "preprint",
    "thesis", "report", "webpage", "presentation", "blogPost",
    "encyclopediaArticle", "dictionaryEntry", "magazineArticle",
    "newspaperArticle", "patent", "standard", "statute", "bill", "case",
    "manuscript", "letter", "interview", "film", "artwork", "audioRecording",
    "videoRecording", "computerProgram", "document", "generic", "podcast",
}

# Zotero 字段名 -> 统一键
ZOTERO_FIELD_MAP = {
    "title": "title",
    "publicationTitle": "journal",
    "bookTitle": "journal",
    "proceedingsTitle": "journal",
    "DOI": "doi",
    "ISBN": "isbn",
    "ISSN": "issn",
    "abstractNote": "abstract",
    "date": "date",
    "url": "url",
    "volume": "volume",
    "issue": "issue",
    "pages": "pages",
    "publisher": "publisher",
    "series": "series",
    "edition": "edition",
}


def _open_zotero_db(sqlite_path: str) -> sqlite3.Connection:
    """以只读方式打开 zotero.sqlite（Zotero 用 WAL，只读连接不干扰运行）。"""
    try:
        return sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        # 兜底：部分环境只读 URI 不可用（如加密/权限），退回普通连接
        return sqlite3.connect(sqlite_path, timeout=10)


def _parse_year(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    m = re.search(r"(19[8-9]\d|20[0-4]\d)", date_str)
    return int(m.group(1)) if m else None


def _author_name(first: str, last: str, field_mode: int) -> str:
    first = (first or "").strip()
    last = (last or "").strip()
    if field_mode == 1:  # 单字段（机构/笔名）
        return last or first or ""
    if field_mode == 0 and first and last:
        return f"{first} {last}"
    return last or first or ""


def _resolve_attachment(att: dict, storage_dir: str, data_dir: str) -> Optional[str]:
    """把 Zotero 附件条目解析为本地 PDF 绝对路径（存在才返回）。"""
    path = (att.get("path") or "").strip()
    link_mode = att.get("linkMode")
    if link_mode == 2:
        # imported file：path = "storage:filename.pdf"，文件在 storage/<key>/<filename>
        filename = path.split(":", 1)[-1].strip()
        cand = os.path.join(storage_dir, att.get("key", ""), filename)
        return cand if os.path.isfile(cand) else None
    if link_mode == 1:
        # linked file：可能是绝对路径或相对路径
        if os.path.isabs(path):
            return path if os.path.isfile(path) else None
        cand = os.path.normpath(os.path.join(data_dir, path))
        return cand if os.path.isfile(cand) else None
    return None


def parse_zotero(data_dir: str) -> dict:
    """解析 Zotero 数据目录，返回 {entries, attachments_found, errors}。

    entries 元素结构：
    {title, authors, year, doi, abstract, journal, tags, pdf_path}
    """
    sqlite_path = os.path.join(data_dir, "zotero.sqlite")
    if not os.path.isfile(sqlite_path):
        return {"entries": [], "attachments_found": 0, "errors": [f"未找到 {sqlite_path}"]}
    storage_dir = os.path.join(data_dir, "storage")
    try:
        conn = _open_zotero_db(sqlite_path)
    except Exception as e:  # noqa: BLE001
        return {"entries": [], "attachments_found": 0, "errors": [f"无法打开 zotero.sqlite: {e}"]}

    try:
        cur = conn.cursor()
        cur.execute("SELECT valueID, value FROM itemDataValues")
        values = dict(cur.fetchall())
        cur.execute("SELECT fieldID, fieldName FROM fields")
        field_names = dict(cur.fetchall())
        cur.execute("SELECT itemID, fieldID, valueID FROM itemData")
        item_data: dict[int, dict[str, str]] = {}
        for item_id, field_id, value_id in cur.fetchall():
            item_data.setdefault(item_id, {})[field_names.get(field_id, str(field_id))] = values.get(value_id, "")
        cur.execute("SELECT creatorID, firstName, lastName, fieldMode FROM creators")
        creators: dict[int, dict] = {}
        for cid, fn, ln, fm in cur.fetchall():
            creators[cid] = {"firstName": fn or "", "lastName": ln or "", "fieldMode": fm or 0}
        cur.execute("SELECT itemID, creatorID, orderIndex FROM itemCreators ORDER BY orderIndex")
        item_creators: dict[int, list] = {}
        for item_id, cid, _oi in cur.fetchall():
            item_creators.setdefault(item_id, []).append(creators.get(cid, {}))
        cur.execute("SELECT itemTypeID, typeName FROM itemTypes")
        item_types = dict(cur.fetchall())
        cur.execute("SELECT itemID, itemTypeID, key FROM items")
        item_rows = cur.fetchall()
        item_keys = {iid: key for iid, _t, key in item_rows}
        item_types_by_id = {iid: item_types.get(t, "") for iid, t, _k in item_rows}
        cur.execute("SELECT itemID, parentItemID, linkMode, contentType, path FROM itemAttachments")
        attachment_by_parent: dict[int, list] = {}
        for item_id, parent_id, link_mode, ctype, path in cur.fetchall():
            if parent_id is None:
                continue
            att = {
                "itemID": item_id,
                "parentItemID": parent_id,
                "linkMode": link_mode,
                "contentType": ctype or "",
                "path": path or "",
                "key": item_keys.get(item_id, ""),
            }
            attachment_by_parent.setdefault(parent_id, []).append(att)
        cur.execute("SELECT collectionID, collectionName FROM collections")
        collection_names = dict(cur.fetchall())
        cur.execute("SELECT collectionID, itemID FROM collectionItems")
        item_collections: dict[int, list] = {}
        for cid, iid in cur.fetchall():
            item_collections.setdefault(iid, []).append(collection_names.get(cid, ""))
        cur.execute("SELECT tagID, name FROM tags")
        tag_names = dict(cur.fetchall())
        cur.execute("SELECT itemID, tagID FROM itemTags")
        item_tags: dict[int, list] = {}
        for iid, tid in cur.fetchall():
            item_tags.setdefault(iid, []).append(tag_names.get(tid, ""))
        conn.close()
    except Exception as e:  # noqa: BLE001
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        return {"entries": [], "attachments_found": 0, "errors": [f"解析失败: {e}"]}

    entries = []
    attachments_found = 0
    for item_id, type_name in item_types_by_id.items():
        if type_name not in ZOTERO_ITEM_TYPES:
            continue
        data = item_data.get(item_id, {})
        fields = {ZOTERO_FIELD_MAP.get(k, k): v for k, v in data.items()}
        title = (fields.get("title") or "").strip()
        if not title:
            continue
        authors = [
            _author_name(c.get("firstName"), c.get("lastName"), c.get("fieldMode") or 0)
            for c in item_creators.get(item_id, [])
        ]
        authors = [a for a in authors if a]
        year = _parse_year(fields.get("date", ""))
        tags = list(item_tags.get(item_id, [])) + list(item_collections.get(item_id, []))
        tags = [t for t in dict.fromkeys(tags) if t]
        # 附件：只认本地 PDF
        pdf_path = None
        for att in attachment_by_parent.get(item_id, []):
            if att["contentType"].lower() == "application/pdf" and att["linkMode"] in (1, 2):
                pdf_path = _resolve_attachment(att, storage_dir, data_dir)
                if pdf_path:
                    attachments_found += 1
                    break
        entries.append(
            {
                "title": title,
                "authors": authors,
                "year": year,
                "doi": (fields.get("doi") or "").strip(),
                "abstract": (fields.get("abstract") or "").strip(),
                "journal": (fields.get("journal") or "").strip(),
                "tags": tags,
                "pdf_path": pdf_path,
            }
        )
    return {"entries": entries, "attachments_found": attachments_found, "errors": []}


# ---------------------------------------------------------------------------
# BibTeX 解析（自包含轻量解析器）
# ---------------------------------------------------------------------------
def _bib_read_value(body: str, i: int) -> tuple[str, int]:
    """从 i 处读取一个 BibTeX 值（{} / "" / 裸词），返回 (值, 新索引)。"""
    n = len(body)
    if i >= n:
        return "", i
    ch = body[i]
    if ch == "{":
        depth = 0
        i += 1
        start = i
        while i < n:
            c = body[i]
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    break
                depth -= 1
            i += 1
        return body[start:i].strip(), i + 1
    if ch == '"':
        i += 1
        start = i
        while i < n and body[i] != '"':
            i += 1
        return body[start:i].strip(), i + 1
    start = i
    while i < n and body[i] not in ",}":
        i += 1
    return body[start:i].strip(), i


def _bib_parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        while i < n and (body[i].isspace() or body[i] == ","):
            i += 1
        start = i
        while i < n and body[i] not in "= \t\n":
            i += 1
        name = body[start:i].strip().lower()
        while i < n and (body[i].isspace() or body[i] == "="):
            i += 1
        if i >= n:
            break
        val, i = _bib_read_value(body, i)
        if name and name not in fields:
            fields[name] = val
    return fields


def _bib_authors(raw: str) -> list[str]:
    """把 "John Smith and Jane Doe" / "Smith, John and Doe, Jane" 解析为姓名列表。"""
    if not raw:
        return []
    out = []
    for part in raw.split(" and "):
        part = part.strip()
        if not part:
            continue
        # 去掉可能的 TeX 花括号（如 {Smith}）
        part = re.sub(r"[{}]", "", part)
        if "," in part:
            last, first = part.split(",", 1)
            name = f"{first.strip()} {last.strip()}".strip()
        else:
            name = part
        # 去掉 "others"
        if name.lower() in ("others", "et al", "et al."):
            name = "et al."
        if name:
            out.append(name)
    return out


def parse_bibtex(content: str) -> list[dict]:
    """解析 BibTeX 内容，返回与 Zotero entries 相同结构的列表。

    用花括号计数扫描条目边界（兼容 author = {A {Deep} Learning} 这类嵌套花括号），
    不依赖无法处理嵌套的正则。
    """
    entries: list[dict] = []
    n = len(content)
    i = 0
    while i < n:
        idx = content.find("@", i)
        if idx == -1:
            break
        # 解析类型名
        j = idx + 1
        while j < n and content[j].isalpha():
            j += 1
        etype = content[idx + 1 : j].lower()
        # 跳过空白到 '{'
        while j < n and content[j].isspace():
            j += 1
        if j >= n or content[j] != "{":
            i = j + 1
            continue
        # 读取 cite key（直到逗号或右花括号）
        j += 1
        start = j
        while j < n and content[j] not in ",}":
            j += 1
        if j >= n:
            break
        if content[j] == "}":
            i = j + 1
            continue
        # 跳过逗号与空白到字段体
        while j < n and (content[j] == "," or content[j].isspace()):
            j += 1
        if j >= n:
            break
        # 用花括号计数读取条目正文
        body_start = j
        depth = 0
        while j < n:
            c = content[j]
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        body = content[body_start:j]
        i = j + 1
        if etype in ("comment", "preamble", "string"):
            continue
        fields = _bib_parse_fields(body)
        title = (fields.get("title") or "").strip()
        if not title:
            continue
        journal = (fields.get("journal") or fields.get("booktitle") or fields.get("howpublished") or "").strip()
        tags = []
        if fields.get("keywords"):
            tags = [t.strip() for t in fields["keywords"].split(",") if t.strip()]
        year_raw = (fields.get("year") or "").strip()
        year = None
        ym = re.search(r"\b(19[8-9]\d|20[0-4]\d)\b", year_raw)
        if ym:
            year = int(ym.group(1))
        entries.append(
            {
                "title": title,
                "authors": _bib_authors(fields.get("author") or ""),
                "year": year,
                "doi": (fields.get("doi") or "").strip(),
                "abstract": (fields.get("abstract") or "").strip(),
                "journal": journal,
                "tags": tags,
                "pdf_path": None,
            }
        )
    return entries


# ---------------------------------------------------------------------------
# RIS 解析
# ---------------------------------------------------------------------------
RIS_TAG_MAP = {
    "TI": "title",
    "T1": "title",
    "AU": "authors",
    "A1": "authors",
    "JO": "journal",
    "JF": "journal",
    "T2": "journal",
    "J2": "journal",
    "DO": "doi",
    "AB": "abstract",
    "N2": "abstract",
    "KW": "tags",
    "PY": "year",
    "PB": "publisher",
}


def parse_ris(content: str) -> list[dict]:
    """解析 RIS 内容，返回与 Zotero entries 相同结构的列表。"""
    entries: list[dict] = []
    current: dict = {}
    for line in content.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^([A-Z0-9]{2})\s+-\s+(.*)$", line)
        if not m:
            # 兼容 "TY  - " 双空格写法
            m2 = re.match(r"^([A-Z0-9]{2})\s*-\s*(.*)$", line)
            if not m2:
                continue
            tag, val = m2.group(1), m2.group(2)
        else:
            tag, val = m.group(1), m.group(2)
        val = val.strip()
        if tag == "TY":
            if current:
                entries.append(current)
            current = {}
        elif tag == "ER":
            if current:
                entries.append(current)
            current = {}
        elif tag in RIS_TAG_MAP:
            key = RIS_TAG_MAP[tag]
            if key == "authors":
                current.setdefault("authors", []).append(val)
            elif key == "tags":
                current.setdefault("tags", []).append(val)
            elif key == "year":
                ym = re.search(r"\b(19[8-9]\d|20[0-4]\d)\b", val)
                if ym:
                    current["year"] = int(ym.group(1))
            else:
                current[key] = val
    if current:
        entries.append(current)

    out = []
    for e in entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "authors": e.get("authors", []),
                "year": e.get("year"),
                "doi": (e.get("doi") or "").strip(),
                "abstract": (e.get("abstract") or "").strip(),
                "journal": (e.get("journal") or "").strip(),
                "tags": e.get("tags", []),
                "pdf_path": None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# 引文导出（BibTeX / RIS，多文献批量）
# ---------------------------------------------------------------------------
def _clean_key(text: str) -> str:
    key = "".join(c for c in text if c.isalnum())
    return key[:6] or "paper"


def paper_to_bibtex(paper, index: int = 0) -> str:
    title = paper.title or "Untitled"
    authors = paper.authors or []
    year = paper.year or ""
    doi = (paper.doi or "").strip()
    author_str = " and ".join(authors) if authors else "Anonymous"
    key = _clean_key(authors[0].split()[0] if authors else title) + str(year or index)
    lines = [
        f"@article{{{key},",
        f"  title = {{{title}}},",
        f"  author = {{{author_str}}},",
    ]
    if paper.abstract:
        abstract = (paper.abstract or "").replace("{", "\\{").replace("}", "\\}")
        lines.append(f"  abstract = {{{abstract}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    lines.append("}")
    return "\n".join(lines)


def paper_to_ris(paper, index: int = 0) -> str:
    title = paper.title or "Untitled"
    authors = paper.authors or []
    year = paper.year or ""
    doi = (paper.doi or "").strip()
    abstract = (paper.abstract or "").strip()
    lines = ["TY  - JOUR"]
    for a in authors:
        lines.append(f"AU  - {a}")
    lines.append(f"TI  - {title}")
    if year:
        lines.append(f"PY  - {year}")
    if doi:
        lines.append(f"DO  - {doi}")
    if abstract:
        lines.append(f"AB  - {abstract}")
    lines.append("ER  - ")
    return "\n".join(lines)
