import json
import os
from pathlib import Path

from qqnt_export_macos.verify import privatize, verify_export


def _fixture(root: Path, html: str) -> None:
    root.mkdir()
    (root / "chat.json").write_text(
        json.dumps({"messages": [{"text": "hello"}]}), encoding="utf-8"
    )
    (root / "chat.jsonl").write_text(
        json.dumps({"text": "hello"}) + "\n", encoding="utf-8"
    )
    (root / "chat.html").write_text(html, encoding="utf-8")


def test_valid_offline_export(tmp_path: Path):
    output = tmp_path / "output"
    _fixture(output, "<script>window.__QQNT_EXPORT_META__={}</script>")
    privatize(output)
    summary, failures = verify_export(output)
    assert failures == []
    assert summary["messages"] == 1
    assert summary["html"] == summary["json"] == summary["jsonl"] == 1


def test_remote_image_is_rejected(tmp_path: Path):
    output = tmp_path / "output"
    _fixture(
        output,
        '<script>window.__QQNT_EXPORT_META__={}</script><img src="https://example.test/x">',
    )
    privatize(output)
    _, failures = verify_export(output)
    assert any("remote auto-loaded media" in failure for failure in failures)


def test_privatize(tmp_path: Path):
    output = tmp_path / "output"
    _fixture(output, "<script>window.__QQNT_EXPORT_META__={}</script>")
    os.chmod(output / "chat.json", 0o644)
    privatize(output)
    assert (output / "chat.json").stat().st_mode & 0o077 == 0


def test_resource_json_is_not_counted_as_conversation(tmp_path: Path):
    output = tmp_path / "output"
    _fixture(output, "<script>window.__QQNT_EXPORT_META__={}</script>")
    resource = output / "resources/animation.json"
    resource.parent.mkdir()
    resource.write_text("[]", encoding="utf-8")
    privatize(output)
    summary, failures = verify_export(output)
    assert failures == []
    assert summary["json"] == 1
    assert summary["resources"] == 1
