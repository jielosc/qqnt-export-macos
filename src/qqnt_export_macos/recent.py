"""Read bounded recent-message views from a private live QQNT mirror."""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import time

from .decrypt import _open_encrypted, _read_key
from .live import LiveDatabaseMirror, discover_active_nt_db, select_mirror_key
from .message_preview import message_preview
from .snapshot import DEFAULT_QQ_ROOT


DEFAULT_BRIDGE_CACHE = Path.home() / "Library/Caches/qqnt-export-macos/bridge"


def _conversation_expression(kind: str) -> str:
    if kind == "c2c":
        return "COALESCE(NULLIF(CAST([40030] AS TEXT), '0'), NULLIF([40021], ''), NULLIF(CAST([40027] AS TEXT), '0'))"
    if kind == "group":
        return "COALESCE(NULLIF(CAST([40027] AS TEXT), '0'), NULLIF([40021], ''), NULLIF(CAST([40030] AS TEXT), '0'))"
    return "'pc'"


def _table_query(kind: str, table: str, cutoff: int, conversation: str | None):
    expression = _conversation_expression(kind)
    where = "[40050] >= ?"
    parameters: list[int | str] = [cutoff]
    if conversation is not None:
        where += f" AND {expression} = ?"
        parameters.append(conversation)
    query = f"""
        SELECT '{kind}' AS kind, [40001] AS message_id, [40003] AS sequence,
               [40020] AS sender_uid, [40033] AS sender_number,
               [40050] AS sent_at, {expression} AS conversation_key,
               [40021] AS peer_uid, [40030] AS peer_number,
               [40093] AS nickname, [40090] AS card,
               [40011] AS message_type, [40800] AS body
        FROM {table}
        WHERE {where}
    """
    return query, parameters


def query_recent(
    connection,
    *,
    minutes: int = 10,
    limit: int = 50,
    conversation_id: str | None = None,
) -> list[dict]:
    """Query recent rows from a SQLCipher or ordinary SQLite connection."""
    minutes = max(1, min(int(minutes), 7 * 24 * 60))
    limit = max(1, min(int(limit), 200))
    kind_filter = key_filter = None
    if conversation_id:
        if ":" not in conversation_id:
            raise ValueError("conversation_id must look like c2c:…, group:…, or dataline:pc")
        kind_filter, key_filter = conversation_id.split(":", 1)
        if kind_filter not in {"c2c", "group", "dataline"} or not key_filter:
            raise ValueError("unsupported conversation_id")

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    definitions = (
        ("c2c", "c2c_msg_table"),
        ("group", "group_msg_table"),
        ("dataline", "dataline_msg_table"),
    )
    cutoff = int(time.time()) - minutes * 60
    queries = []
    parameters: list[int | str] = []
    for kind, table in definitions:
        if table not in tables or (kind_filter and kind != kind_filter):
            continue
        query, values = _table_query(kind, table, cutoff, key_filter)
        queries.append(query)
        parameters.extend(values)
    if not queries:
        return []
    sql = " UNION ALL ".join(queries) + " ORDER BY sent_at DESC, message_id DESC LIMIT ?"
    parameters.append(limit)
    cursor = connection.execute(sql, parameters)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


class QQRecentReader:
    """Refresh a live mirror and return sanitized recent-message records."""

    def __init__(
        self,
        key_path: Path,
        *,
        root: Path = DEFAULT_QQ_ROOT,
        cache_dir: Path = DEFAULT_BRIDGE_CACHE,
        account: str | None = None,
    ):
        self.key_path = key_path.expanduser().resolve()
        self.nt_db = discover_active_nt_db(root, account)
        cache_root = cache_dir.expanduser().resolve()
        cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(cache_root, 0o700)
        account_cache = cache_root / self.nt_db.parent.name
        self.mirror = LiveDatabaseMirror(self.nt_db / "nt_msg.db", account_cache)

    def _connection(self):
        database = self.mirror.refresh()
        selected = select_mirror_key(database, self.key_path)
        return _open_encrypted(database, _read_key(selected), read_only=True)

    def status(self) -> dict:
        started = time.monotonic()
        connection = self._connection()
        try:
            latest = 0
            for table in ("c2c_msg_table", "group_msg_table", "dataline_msg_table"):
                try:
                    value = connection.execute(
                        f"SELECT MAX([40050]) FROM {table}"
                    ).fetchone()[0]
                except Exception:
                    continue
                latest = max(latest, int(value or 0))
        finally:
            connection.close()
        return {
            "ok": True,
            "transport": "local-stdio",
            "read_only": True,
            "latest_message_at": datetime.fromtimestamp(latest).astimezone().isoformat()
            if latest
            else None,
            "latest_message_age_seconds": max(0, int(time.time()) - latest)
            if latest
            else None,
            "refresh_ms": round((time.monotonic() - started) * 1000),
        }

    def recent(
        self,
        *,
        minutes: int = 10,
        limit: int = 50,
        conversation_id: str | None = None,
    ) -> dict:
        started = time.monotonic()
        connection = self._connection()
        try:
            rows = query_recent(
                connection,
                minutes=minutes,
                limit=limit,
                conversation_id=conversation_id,
            )
        finally:
            connection.close()
        messages = []
        for row in reversed(rows):
            key = str(row.pop("conversation_key") or "unknown")
            body = row.pop("body", None)
            kind = row["kind"]
            sender = row.pop("card") or row.pop("nickname")
            sender = sender or row.get("sender_number") or row.get("sender_uid")
            sent_at = int(row["sent_at"] or 0)
            messages.append(
                {
                    "conversation_id": f"{kind}:{key}",
                    "message_id": str(row["message_id"]),
                    "timestamp": sent_at,
                    "time": datetime.fromtimestamp(sent_at).astimezone().isoformat()
                    if sent_at
                    else None,
                    "sender": str(sender) if sender is not None else "unknown",
                    "sender_number": row.get("sender_number"),
                    "content": message_preview(body),
                }
            )
        return {
            "synced_at": datetime.now().astimezone().isoformat(),
            "refresh_ms": round((time.monotonic() - started) * 1000),
            "count": len(messages),
            "messages": messages,
        }


def reader_from_environment() -> QQRecentReader:
    key = os.environ.get("QQNT_KEY_PATH")
    if not key:
        raise RuntimeError("QQNT_KEY_PATH is required")
    root = Path(os.environ.get("QQNT_DATA_ROOT", str(DEFAULT_QQ_ROOT)))
    cache = Path(os.environ.get("QQNT_CACHE_DIR", str(DEFAULT_BRIDGE_CACHE)))
    return QQRecentReader(
        Path(key), root=root, cache_dir=cache, account=os.environ.get("QQNT_ACCOUNT")
    )


def install_bridge_key(
    candidates: Path,
    destination: Path,
    *,
    root: Path = DEFAULT_QQ_ROOT,
    cache_dir: Path = DEFAULT_BRIDGE_CACHE,
    account: str | None = None,
) -> str:
    """Validate candidates against the live mirror and copy only the valid key."""
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    reader = QQRecentReader(
        candidates, root=root, cache_dir=cache_dir, account=account
    )
    database = reader.mirror.refresh()
    selected = select_mirror_key(database, candidates)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    shutil.copyfile(selected, destination)
    os.chmod(destination, 0o600)
    return hashlib.sha256(destination.read_bytes()).hexdigest()[:12]
