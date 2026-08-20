"""安全加固回归测试：插件 zip / Skill 压缩包的路径穿越防护。"""

import io
import json
import os
import shutil
import tempfile
import zipfile

import pytest

from app.agent.plugin_manager import PluginManager, PluginError
from app.agent import skill_store


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            zf.writestr(name, content)
    return buf.getvalue()


def test_plugin_install_rejects_path_traversal_zip() -> None:
    tmp = tempfile.mkdtemp(prefix="plugin_hardening_")
    try:
        payload = _zip_bytes(
            [
                ("plugin.json", json.dumps({"name": "demo", "version": "1.0.0", "provides": {}}).encode()),
                ("../escape.txt", b"evil"),
            ]
        )
        with pytest.raises(PluginError):
            PluginManager(plugins_dir=tmp).install_from_zip(payload)
        assert not os.path.exists(os.path.join(os.path.dirname(tmp), "escape.txt"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_skill_extract_skips_path_traversal_member() -> None:
    skill_md = b"---\nname: harden-skill\n---\nTest skill"
    payload = _zip_bytes(
        [
            ("skills/MySkill/SKILL.md", skill_md),
            ("skills/MySkill/../../../escape.txt", b"evil"),
        ]
    )
    storage_root = os.environ["STORAGE_DIR"]
    outside = os.path.join(os.path.dirname(storage_root.rstrip("/\\")), "escape.txt")
    try:
        skills = skill_store.extract_skills(payload, "skill.zip")
        assert skills
        assert not os.path.exists(outside)
        assert not os.path.exists(os.path.join(storage_root, "escape.txt"))
    finally:
        if os.path.exists(outside):
            os.remove(outside)
