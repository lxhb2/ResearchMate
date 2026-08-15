"""可移植的数据库列类型（同时兼容 SQLite 与 PostgreSQL）。

轻量化改造：不再依赖 PostgreSQL 的 UUID/JSONB/ARRAY/Vector 专用类型，
统一使用跨库类型，保证 SQLite 单文件也能运行。
"""
import uuid

from sqlalchemy import String, Text
from sqlalchemy.types import JSON


def uuid_str() -> str:
    """生成 UUID 字符串主键默认值。"""
    return str(uuid.uuid4())


# 主键/外键统一用 36 位 UUID 字符串（跨库兼容）
GUID = String(36)

# JSON 字段统一用通用 JSON 类型（SQLite 存为 TEXT，PG 存为 JSON）
JSONType = JSON


def make_embedding(impl=Text) -> type:
    """返回一个将向量(list[float])序列化为文本的列类型工厂。

    轻量化：向量不再用 pgvector 的 Vector 列，而是序列化为 JSON 文本，
    检索时在内存中计算余弦相似度（个人文献库规模足够）。
    """
    from sqlalchemy.types import TypeDecorator

    class VectorJson(TypeDecorator):
        cache_ok = True

        def process_bind_param(self, value, dialect):
            if value is None:
                return None
            import json
            return json.dumps(value)

        def process_result_value(self, value, dialect):
            if value is None:
                return None
            try:
                import json
                return json.loads(value)
            except Exception:  # noqa: BLE001
                return None

    VectorJson.impl = impl
    return VectorJson


# 向量列：存为 JSON 文本
VectorJson = make_embedding(Text)