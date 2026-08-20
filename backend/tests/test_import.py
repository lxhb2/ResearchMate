"""Zotero 导入解析测试，重点覆盖数据库被 Zotero 占用时的快照兜底。"""

import os
import shutil
import sqlite3
import tempfile

from app.services import import_service


def _build_zotero_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INTEGER);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, orderIndex INTEGER);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, key TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER);
            """
        )
        conn.executemany(
            "INSERT INTO itemDataValues (valueID, value) VALUES (?, ?)",
            [(1, "Test Paper"), (2, "2023"), (3, "10.1000/test"), (4, "Orphan Paper")],
        )
        conn.executemany(
            "INSERT INTO fields (fieldID, fieldName) VALUES (?, ?)",
            [(1, "title"), (2, "date"), (3, "DOI")],
        )
        conn.executemany(
            "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
            [(1, 1, 1), (1, 2, 2), (1, 3, 3), (3, 1, 4)],
        )
        conn.executemany(
            "INSERT INTO creators (creatorID, firstName, lastName, fieldMode) VALUES (?, ?, ?, ?)",
            [(1, "Jane", "Doe", 0)],
        )
        conn.execute(
            "INSERT INTO itemCreators (itemID, creatorID, orderIndex) VALUES (1, 1, 0)"
        )
        conn.execute(
            "INSERT INTO itemTypes (itemTypeID, typeName) VALUES (1, 'journalArticle')"
        )
        conn.execute("INSERT INTO itemTypes (itemTypeID, typeName) VALUES (3, 'attachment')")
        conn.execute("INSERT INTO items (itemID, itemTypeID, key) VALUES (1, 1, 'KEY')")
        conn.execute("INSERT INTO items (itemID, itemTypeID, key) VALUES (2, 3, 'ATTKEY')")
        conn.execute("INSERT INTO items (itemID, itemTypeID, key) VALUES (3, 3, 'ORPHKEY')")
        conn.executemany(
            "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path) VALUES (?, ?, ?, ?, ?)",
            [
                (2, 1, 0, "application/pdf", "storage:test.pdf"),
                (3, None, 0, "application/pdf", "storage:orphan.pdf"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_parse_zotero_uses_snapshot_when_db_locked() -> None:
    data_dir = tempfile.mkdtemp(prefix="zotero_test_")
    lock = None
    try:
        _build_zotero_db(os.path.join(data_dir, "zotero.sqlite"))
        storage_dir = os.path.join(data_dir, "storage")
        os.makedirs(os.path.join(storage_dir, "ATTKEY"))
        os.makedirs(os.path.join(storage_dir, "ORPHKEY"))
        with open(os.path.join(storage_dir, "ATTKEY", "test.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 test")
        with open(os.path.join(storage_dir, "ORPHKEY", "orphan.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 orphan")
        lock = sqlite3.connect(os.path.join(data_dir, "zotero.sqlite"), timeout=1)
        lock.execute("BEGIN EXCLUSIVE")

        result = import_service.parse_zotero(data_dir)

        assert result["errors"] == []
        assert result["attachments_found"] == 2
        by_title = {e["title"]: e for e in result["entries"]}
        assert by_title["Test Paper"]["doi"] == "10.1000/test"
        assert by_title["Test Paper"]["pdf_path"].endswith("test.pdf")
        assert by_title["Orphan Paper"]["pdf_path"].endswith("orphan.pdf")
        assert all(os.path.isfile(e["pdf_path"]) for e in result["entries"])
    finally:
        if lock is not None:
            lock.rollback()
            lock.close()
        shutil.rmtree(data_dir, ignore_errors=True)
