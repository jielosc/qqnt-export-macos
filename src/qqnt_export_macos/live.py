"""Consistent, private mirrors of a running QQNT database and its WAL."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import fcntl
import json
import os
from pathlib import Path
import time

from .decrypt import HEADER_SIZE, _open_encrypted, _read_key
from .snapshot import DEFAULT_QQ_ROOT


@dataclass(frozen=True)
class FileState:
    device: int
    inode: int
    size: int
    mtime_ns: int

    @classmethod
    def read(cls, path: Path) -> "FileState":
        stat = path.stat()
        return cls(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def discover_active_nt_db(root: Path = DEFAULT_QQ_ROOT, account: str | None = None) -> Path:
    """Find an account nt_db, preferring the database with newest activity."""
    root = root.expanduser().resolve()
    if account:
        candidate = root / account / "nt_db"
        if not (candidate / "nt_msg.db").is_file():
            raise FileNotFoundError(f"account database not found: {account}")
        return candidate
    candidates = [
        path / "nt_db"
        for path in root.glob("nt_qq_*")
        if (path / "nt_db/nt_msg.db").is_file()
    ]
    if not candidates:
        raise FileNotFoundError("no QQNT account message databases found")

    def activity(path: Path) -> tuple[int, int]:
        database = path / "nt_msg.db"
        wal = path / "nt_msg.db-wal"
        modified = max(
            database.stat().st_mtime_ns,
            wal.stat().st_mtime_ns if wal.is_file() else 0,
        )
        return modified, database.stat().st_size

    return max(candidates, key=activity)


class LiveDatabaseMirror:
    """Maintain a stripped QQNT database mirror without touching the source."""

    def __init__(self, source: Path, cache_dir: Path):
        self.source = source.expanduser().resolve()
        self.cache_dir = cache_dir.expanduser().resolve()
        self.database = self.cache_dir / self.source.name
        self.metadata = self.cache_dir / f"{self.source.name}.source.json"
        self.lock = self.cache_dir / f"{self.source.name}.lock"

    @staticmethod
    def _same(left: FileState, right: FileState) -> bool:
        return left == right

    def _cached_state(self) -> FileState | None:
        try:
            data = json.loads(self.metadata.read_text(encoding="utf-8"))
            if data.get("source") != str(self.source):
                return None
            return FileState(**data["state"])
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _copy_stable(source: Path, destination: Path, offset: int = 0) -> FileState:
        before = FileState.read(source)
        with source.open("rb") as incoming, destination.open("wb") as outgoing:
            if offset:
                header = incoming.read(offset)
                if len(header) != offset or b"QQ_NT DB" not in header:
                    raise ValueError(f"{source.name} has no valid QQNT header")
            while chunk := incoming.read(8 * 1024 * 1024):
                outgoing.write(chunk)
        os.chmod(destination, 0o600)
        after = FileState.read(source)
        if before != after:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"{source.name} changed while it was copied")
        return after

    def _write_metadata(self, state: FileState) -> None:
        temporary = self.metadata.with_suffix(".json.next")
        temporary.write_text(
            json.dumps({"source": str(self.source), "state": asdict(state)}) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.metadata)

    def refresh(self, *, force: bool = False, attempts: int = 5) -> Path:
        """Refresh the local base/WAL pair, retrying concurrent checkpoints."""
        if not self.source.is_file():
            raise FileNotFoundError(self.source)
        self.cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.cache_dir, 0o700)
        with self.lock.open("a+b") as lock_file:
            os.chmod(self.lock, 0o600)
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            for attempt in range(attempts):
                source_state = FileState.read(self.source)
                cached_state = self._cached_state()
                rebuild = force or not self.database.is_file() or cached_state != source_state
                next_database = self.database.with_suffix(".db.next")
                next_wal = self.database.with_name(self.database.name + "-wal.next")
                try:
                    if rebuild:
                        copied_state = self._copy_stable(
                            self.source, next_database, HEADER_SIZE
                        )
                    else:
                        copied_state = source_state

                    source_wal = self.source.with_name(self.source.name + "-wal")
                    if source_wal.is_file():
                        self._copy_stable(source_wal, next_wal)
                        has_wal = True
                    else:
                        has_wal = False

                    if FileState.read(self.source) != copied_state:
                        raise RuntimeError("database checkpoint raced with mirror refresh")

                    if rebuild:
                        os.replace(next_database, self.database)
                    target_wal = self.database.with_name(self.database.name + "-wal")
                    if has_wal:
                        os.replace(next_wal, target_wal)
                    else:
                        target_wal.unlink(missing_ok=True)
                    self.database.with_name(self.database.name + "-shm").unlink(
                        missing_ok=True
                    )
                    self._write_metadata(copied_state)
                    return self.database
                except (FileNotFoundError, RuntimeError):
                    next_database.unlink(missing_ok=True)
                    next_wal.unlink(missing_ok=True)
                    if attempt + 1 == attempts:
                        raise RuntimeError(
                            f"could not obtain a stable mirror of {self.source.name}"
                        )
                    time.sleep(0.05 * (attempt + 1))
        raise RuntimeError("unreachable")


def select_mirror_key(database: Path, key_path: Path) -> Path:
    """Select exactly one key without revealing candidate contents."""
    key_path = key_path.expanduser().resolve()
    candidates = sorted(key_path.glob("*.key")) if key_path.is_dir() else [key_path]
    accepted: list[Path] = []
    for candidate in candidates:
        connection = None
        try:
            connection = _open_encrypted(
                database, _read_key(candidate), read_only=True
            )
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            accepted.append(candidate)
        except Exception:
            pass
        finally:
            if connection is not None:
                connection.close()
    if len(accepted) != 1:
        raise RuntimeError(
            f"expected exactly one valid key candidate; found {len(accepted)}"
        )
    return accepted[0]
