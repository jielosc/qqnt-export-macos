"""Decrypt macOS QQNT database snapshots with SQLCipher."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable


HEADER_SIZE = 1024
DEFAULT_DATABASES = ("nt_msg.db", "profile_info.db", "group_info.db", "emoji.db")


def _sqlcipher_module():
    try:
        import sqlcipher3.dbapi2 as sqlcipher
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "SQLCipher support is missing; install with "
            "`pip install 'qqnt-export-macos[decrypt]'`"
        ) from exc
    return sqlcipher


def _read_key(path: Path) -> str:
    raw = path.read_bytes()
    try:
        key = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path.name} is not an ASCII SQLCipher key") from exc
    if not key:
        raise ValueError(f"{path.name} is empty")
    return key


def _open_encrypted(path: Path, key: str):
    sqlcipher = _sqlcipher_module()
    connection = sqlcipher.connect(str(path), isolation_level=None)
    escaped_key = key.replace("'", "''")
    # QQNT requires the page-size pragma before the key pragma.
    connection.execute("PRAGMA cipher_page_size = 4096")
    connection.execute(f"PRAGMA key = '{escaped_key}'")
    connection.execute("PRAGMA kdf_iter = 4000")
    connection.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1")
    connection.execute("PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512")
    connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return connection


def _strip_header(source: Path, destination: Path) -> None:
    with source.open("rb") as input_file:
        header = input_file.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE or b"QQ_NT DB" not in header:
            raise ValueError(f"{source.name} has no valid QQNT header")
        with destination.open("xb") as output_file:
            while chunk := input_file.read(8 * 1024 * 1024):
                output_file.write(chunk)
    os.chmod(destination, 0o600)


def key_opens_database(database: Path, key_file: Path) -> bool:
    key = _read_key(key_file)
    with tempfile.TemporaryDirectory(prefix="qqnt-key-test-") as directory:
        stripped = Path(directory) / database.name
        _strip_header(database, stripped)
        connection = None
        try:
            connection = _open_encrypted(stripped, key)
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return True
        except Exception:
            return False
        finally:
            if connection is not None:
                connection.close()


def select_key(database: Path, key_path: Path) -> Path:
    candidates = (
        sorted(key_path.glob("*.key")) if key_path.is_dir() else [key_path]
    )
    accepted = [path for path in candidates if key_opens_database(database, path)]
    if len(accepted) != 1:
        raise RuntimeError(
            f"expected exactly one valid key candidate; found {len(accepted)}"
        )
    return accepted[0]


def _decrypt_one(source: Path, destination: Path, key: str, work: Path) -> int:
    stripped = work / source.name
    _strip_header(source, stripped)
    connection = None
    attached = False
    try:
        connection = _open_encrypted(stripped, key)
        schema_count = int(
            connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        )
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        connection.execute("ATTACH DATABASE ? AS plaintext KEY ''", (str(destination),))
        attached = True
        connection.execute("SELECT sqlcipher_export('plaintext')").fetchone()
        connection.execute(f"PRAGMA plaintext.user_version = {user_version}")
        connection.execute(f"PRAGMA plaintext.application_id = {application_id}")
        connection.execute("DETACH DATABASE plaintext")
        attached = False
        connection.commit()
    finally:
        if connection is not None:
            if attached:
                try:
                    connection.execute("DETACH DATABASE plaintext")
                except Exception:
                    pass
            connection.close()
        stripped.unlink(missing_ok=True)

    os.chmod(destination, 0o600)
    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as plain:
        result = plain.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"{source.name} quick_check failed: {result}")
    return schema_count


def decrypt_directory(
    source: Path,
    destination: Path,
    key_path: Path,
    database_names: Iterable[str] = DEFAULT_DATABASES,
) -> tuple[Path, dict[str, int]]:
    """Decrypt required databases without modifying the source snapshot."""
    os.umask(0o077)
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    if source == destination or source in destination.parents:
        raise ValueError("destination must not be inside the encrypted source")

    names = tuple(database_names)
    missing = [name for name in names if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing databases: {', '.join(missing)}")
    for suffix in ("-wal", "-journal"):
        live = [
            name + suffix
            for name in names
            if (source / (name + suffix)).is_file()
            and (source / (name + suffix)).stat().st_size
        ]
        if live:
            raise RuntimeError(
                "snapshot contains non-empty live journals: " + ", ".join(live)
            )

    selected = select_key(source / "nt_msg.db", key_path.resolve())
    key = _read_key(selected)
    destination.mkdir(mode=0o700, parents=True)
    results = {}
    with tempfile.TemporaryDirectory(
        prefix="qqnt-decrypt-", dir=destination.parent
    ) as temporary:
        work = Path(temporary)
        for name in names:
            try:
                results[name] = _decrypt_one(
                    source / name, destination / name, key, work
                )
            except Exception:
                (destination / name).unlink(missing_ok=True)
                raise
    return selected, results
