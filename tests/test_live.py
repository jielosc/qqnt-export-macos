import os
from pathlib import Path

from qqnt_export_macos.live import LiveDatabaseMirror, discover_active_nt_db


def _database(path: Path, payload: bytes = b"encrypted") -> None:
    path.parent.mkdir(parents=True)
    path.write_bytes(b"QQ_NT DB" + b"\0" * (1024 - 8) + payload)


def test_live_mirror_strips_header_and_copies_wal(tmp_path):
    source = tmp_path / "source" / "nt_msg.db"
    _database(source)
    source.with_name("nt_msg.db-wal").write_bytes(b"wal-data")

    mirror = LiveDatabaseMirror(source, tmp_path / "private-cache")
    result = mirror.refresh()

    assert result.read_bytes() == b"encrypted"
    assert result.with_name("nt_msg.db-wal").read_bytes() == b"wal-data"
    assert result.stat().st_mode & 0o077 == 0
    assert mirror.cache_dir.stat().st_mode & 0o077 == 0


def test_discover_active_account_uses_wal_activity(tmp_path):
    older = tmp_path / "nt_qq_old" / "nt_db" / "nt_msg.db"
    newer = tmp_path / "nt_qq_new" / "nt_db" / "nt_msg.db"
    _database(older)
    _database(newer)
    os.utime(older, ns=(1_000, 1_000))
    os.utime(newer, ns=(2_000, 2_000))
    wal = older.with_name("nt_msg.db-wal")
    wal.write_bytes(b"new activity")
    os.utime(wal, ns=(3_000, 3_000))

    assert discover_active_nt_db(tmp_path) == older.parent
    assert discover_active_nt_db(tmp_path, "nt_qq_new") == newer.parent
