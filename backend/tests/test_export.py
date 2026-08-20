"""Markdown to DOCX export smoke test."""
from app.services.export_service import md_to_docx_bytes


def test_md_to_docx_bytes() -> None:
    data = md_to_docx_bytes("# 标题\n\n正文内容 *强调*\n\n- 第一项\n- 第二项", "演示文档")
    assert data[:2] == b"PK"
    assert len(data) > 1000
