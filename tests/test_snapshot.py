import json
from pathlib import Path

import pytest

import qqnt_export_macos.snapshot as snapshot_module
from qqnt_export_macos.snapshot import (
    create_snapshot,
    discover_accounts,
    find_runtime_wrapper,
)


def test_find_hot_update_wrapper(tmp_path: Path):
    root = tmp_path / "QQ"
    wrapper = (
        root
        / "versions/7.0.1-test/QQUpdate.app/Contents/Resources/app/wrapper.node"
    )
    wrapper.parent.mkdir(parents=True)
    wrapper.write_bytes(b"macho")
    (root / "versions/config.json").write_text(
        json.dumps({"curVersion": "7.0.1-test"}), encoding="utf-8"
    )
    assert find_runtime_wrapper(root) == wrapper


def test_discover_accounts(tmp_path: Path):
    valid = tmp_path / "nt_qq_example/nt_db"
    valid.mkdir(parents=True)
    (valid / "nt_msg.db").write_bytes(b"db")
    (tmp_path / "nt_qq_empty").mkdir()
    assert discover_accounts(tmp_path) == [valid]


def test_database_snapshot_is_private(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    database = source / "nt_qq_demo/nt_db/nt_msg.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"database")
    monkeypatch.setattr(snapshot_module, "qq_is_running", lambda: False)

    destination = tmp_path / "snapshot"
    manifest = create_snapshot(destination, source, "databases")
    copied = destination / "nt_qq_demo/nt_db/nt_msg.db"
    assert copied.read_bytes() == b"database"
    assert manifest["databases"][0]["path"] == "nt_qq_demo/nt_db/nt_msg.db"
    assert copied.stat().st_mode & 0o077 == 0


def test_snapshot_rejects_live_wal(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    database = source / "nt_qq_demo/nt_db/nt_msg.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"database")
    (database.parent / "nt_msg.db-wal").write_bytes(b"live")
    monkeypatch.setattr(snapshot_module, "qq_is_running", lambda: False)

    with pytest.raises(RuntimeError, match="non-empty database journals"):
        create_snapshot(tmp_path / "snapshot", source, "databases")
