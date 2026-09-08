"""Read bounded recent-message views from a private live QQNT mirror."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from .decrypt import _open_encrypted, _read_key
from .live import LiveDatabaseMirror, discover_active_nt_db, select_mirror_key
from .message_preview import message_metadata, message_preview
from .snapshot import DEFAULT_QQ_ROOT


DEFAULT_BRIDGE_CACHE = Path.home() / "Library/Caches/qqnt-export-macos/bridge"
MAX_LOOKBACK_MINUTES = 20 * 365 * 24 * 60
MAX_MESSAGE_PAGE_SIZE = 1000
MAX_CONVERSATION_LIMIT = 5000
_MESSAGE_KINDS = {"c2c", "group", "dataline"}


@dataclass(frozen=True)
class RecentQueryPage:
    rows: list[dict]
    cutoff: int
    limit: int
    has_more: bool
    next_cursor: str | None


def _encode_cursor(*, cutoff: int, row: dict, conversation_id: str | None) -> str:
    payload = {
        "v": 1,
        "cutoff": cutoff,
        "sent_at": int(row["sent_at"]),
        "message_id": int(row["message_id"]),
        "kind": str(row["kind"]),
        "conversation_id": conversation_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, int, int, str, str | None]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        )
        cutoff = int(payload["cutoff"])
        sent_at = int(payload["sent_at"])
        message_id = int(payload["message_id"])
        kind = str(payload["kind"])
        conversation_id = payload.get("conversation_id")
        if conversation_id is not None:
            conversation_id = str(conversation_id)
        if payload.get("v") != 1 or kind not in _MESSAGE_KINDS:
            raise ValueError
        if cutoff < 0 or sent_at < cutoff:
            raise ValueError
        return cutoff, sent_at, message_id, kind, conversation_id
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise ValueError("invalid message cursor") from exc


def _normalize_minutes(minutes: int) -> int:
    return max(1, min(int(minutes), MAX_LOOKBACK_MINUTES))


def _normalize_message_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_MESSAGE_PAGE_SIZE))


def _conversation_filter(conversation_id: str | None) -> tuple[str | None, str | None]:
    if not conversation_id:
        return None, None
    if ":" not in conversation_id:
        raise ValueError("conversation_id must look like c2c:…, group:…, or dataline:pc")
    kind, key = conversation_id.split(":", 1)
    if kind not in _MESSAGE_KINDS or not key:
        raise ValueError("unsupported conversation_id")
    return kind, key


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
    cursor: str | None = None,
) -> list[dict]:
    """Query recent rows from a SQLCipher or ordinary SQLite connection."""
    return query_recent_page(
        connection,
        minutes=minutes,
        limit=limit,
        conversation_id=conversation_id,
        cursor=cursor,
    ).rows


def query_recent_page(
    connection,
    *,
    minutes: int = 10,
    limit: int = 50,
    conversation_id: str | None = None,
    cursor: str | None = None,
) -> RecentQueryPage:
    """Query one stable, newest-to-oldest page of recent message rows."""
    minutes = _normalize_minutes(minutes)
    limit = _normalize_message_limit(limit)
    kind_filter, key_filter = _conversation_filter(conversation_id)
    boundary = _decode_cursor(cursor) if cursor else None
    cutoff = boundary[0] if boundary else int(time.time()) - minutes * 60
    if boundary and boundary[4] != conversation_id:
        raise ValueError("message cursor belongs to a different conversation")

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
    queries = []
    parameters: list[int | str] = []
    for kind, table in definitions:
        if table not in tables or (kind_filter and kind != kind_filter):
            continue
        query, values = _table_query(kind, table, cutoff, key_filter)
        queries.append(query)
        parameters.extend(values)
    if not queries:
        return RecentQueryPage([], cutoff, limit, False, None)
    sql = "SELECT * FROM (" + " UNION ALL ".join(queries) + ") AS recent"
    if boundary:
        _, sent_at, message_id, kind, _ = boundary
        sql += """
            WHERE sent_at < ?
               OR (sent_at = ? AND message_id < ?)
               OR (sent_at = ? AND message_id = ? AND kind < ?)
        """
        parameters.extend([sent_at, sent_at, message_id, sent_at, message_id, kind])
    sql += " ORDER BY sent_at DESC, message_id DESC, kind DESC LIMIT ?"
    parameters.append(limit + 1)
    cursor = connection.execute(sql, parameters)
    columns = [item[0] for item in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode_cursor(cutoff=cutoff, row=rows[-1], conversation_id=conversation_id)
        if has_more
        else None
    )
    return RecentQueryPage(rows, cutoff, limit, has_more, next_cursor)


def query_message_range(
    connection,
    *,
    start_timestamp: int,
    end_timestamp: int,
    conversation_id: str,
) -> list[dict]:
    """Read all messages in one exact half-open interval for one conversation."""
    start_timestamp = int(start_timestamp)
    end_timestamp = int(end_timestamp)
    if start_timestamp < 0 or start_timestamp >= end_timestamp:
        raise ValueError("invalid message time range")
    kind, conversation_key = _conversation_filter(conversation_id)
    assert kind is not None and conversation_key is not None
    table = {
        "c2c": "c2c_msg_table",
        "group": "group_msg_table",
        "dataline": "dataline_msg_table",
    }[kind]
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if table not in tables:
        return []

    expression = _conversation_expression(kind)
    query, parameters = _table_query(kind, table, start_timestamp, conversation_key)
    query += " AND [40050] < ?"
    parameters.append(end_timestamp)
    query += " ORDER BY [40050] ASC, [40001] ASC"
    cursor = connection.execute(query, parameters)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_conversations(
    connection, *, minutes: int = 24 * 60, limit: int = 100
) -> list[dict]:
    """Aggregate active conversations without imposing a message-row cap."""
    cutoff = int(time.time()) - _normalize_minutes(minutes) * 60
    limit = max(1, min(int(limit), MAX_CONVERSATION_LIMIT))
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
    queries = []
    parameters: list[int] = []
    for kind, table in definitions:
        if table not in tables:
            continue
        expression = _conversation_expression(kind)
        queries.append(
            f"""
                SELECT '{kind}' AS kind, {expression} AS conversation_key,
                       MAX([40050]) AS latest_at, COUNT(*) AS message_count
                FROM {table}
                WHERE [40050] >= ? AND {expression} IS NOT NULL
                GROUP BY {expression}
            """
        )
        parameters.append(cutoff)
    if not queries:
        return []
    sql = (
        "SELECT * FROM ("
        + " UNION ALL ".join(queries)
        + ") AS conversations ORDER BY latest_at DESC, kind, conversation_key LIMIT ?"
    )
    parameters.append(limit)
    cursor = connection.execute(sql, parameters)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_group_names(connection) -> dict[str, str]:
    """Read group-number to display-name mappings from QQNT group metadata."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    names: dict[str, str] = {}
    for table in ("group_list", "group_detail_info_ver1"):
        if table not in tables:
            continue
        for group_number, display_name in connection.execute(
            f"SELECT CAST([60001] AS TEXT), [60007] FROM {table}"
        ).fetchall():
            name = str(display_name or "").strip()
            if group_number and name:
                names.setdefault(str(group_number), name)
    return names


def query_group_member_names(connection, group_id: str) -> dict[str, str]:
    """Read group-member display names keyed by QQNT UID and UIN."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "group_member3" not in tables:
        return {}

    names: dict[str, str] = {}
    rows = connection.execute(
        """
        SELECT [64003] AS nickname, [20002] AS card,
               CAST([1000] AS TEXT) AS uid, CAST([1002] AS TEXT) AS uin
        FROM group_member3
        WHERE CAST([60001] AS TEXT) = ?
        """,
        (group_id,),
    ).fetchall()
    for nickname, card, uid, uin in rows:
        name = str(nickname or "").strip() or str(card or "").strip()
        if not name:
            continue
        for identity in (uid, uin):
            key = str(identity or "").strip()
            if key:
                names.setdefault(key, name)
    return names


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
        group_database = self.nt_db / "group_info.db"
        self.group_mirror = (
            LiveDatabaseMirror(group_database, account_cache)
            if group_database.is_file()
            else None
        )

    def _mirror_connection(self, mirror: LiveDatabaseMirror):
        database = mirror.refresh()
        selected = select_mirror_key(database, self.key_path)
        return _open_encrypted(database, _read_key(selected), read_only=True)

    def _connection(self):
        return self._mirror_connection(self.mirror)

    def group_names(self) -> dict[str, str]:
        if self.group_mirror is None:
            return {}
        connection = self._mirror_connection(self.group_mirror)
        try:
            return query_group_names(connection)
        finally:
            connection.close()

    def resolve_group_name(
        self, query: str, allowed_ids: set[str] | None = None
    ) -> tuple[str, str]:
        requested = query.strip()
        if not requested:
            raise ValueError("conversation_name cannot be empty")
        names = self.group_names()
        if allowed_ids is not None:
            names = {
                key: name
                for key, name in names.items()
                if f"group:{key}" in allowed_ids
            }
        explicit_key = requested.removeprefix("group:")
        if explicit_key in names:
            return f"group:{explicit_key}", names[explicit_key]

        folded = requested.casefold()
        exact = [(key, name) for key, name in names.items() if name.casefold() == folded]
        matches = exact or [
            (key, name) for key, name in names.items() if folded in name.casefold()
        ]
        if not matches:
            raise ValueError(f"no QQ group matches name: {requested}")
        if len(matches) > 1:
            candidates = ", ".join(
                f"{name} (group:{key})" for key, name in sorted(matches)[:20]
            )
            raise ValueError(f"ambiguous QQ group name; choose one: {candidates}")
        key, name = matches[0]
        return f"group:{key}", name

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
        conversation_name: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        if conversation_id and conversation_name:
            raise ValueError("use conversation_id or conversation_name, not both")
        resolved_name = None
        if conversation_name:
            conversation_id, resolved_name = self.resolve_group_name(conversation_name)
        started = time.monotonic()
        connection = self._connection()
        try:
            page = query_recent_page(
                connection,
                minutes=minutes,
                limit=limit,
                conversation_id=conversation_id,
                cursor=cursor,
            )
        finally:
            connection.close()
        group_names = (
            self.group_names()
            if any(row["kind"] == "group" for row in page.rows)
            else {}
        )
        member_names_by_group: dict[str, dict[str, str]] = {}
        if self.group_mirror is not None:
            group_ids = {
                str(row["conversation_key"])
                for row in page.rows
                if row["kind"] == "group" and row.get("conversation_key")
            }
            if group_ids:
                member_connection = self._mirror_connection(self.group_mirror)
                try:
                    member_names_by_group = {
                        group_id: query_group_member_names(member_connection, group_id)
                        for group_id in group_ids
                    }
                finally:
                    member_connection.close()
        messages = []
        for row in reversed(page.rows):
            key = str(row.pop("conversation_key") or "unknown")
            body = row.pop("body", None)
            kind = row["kind"]
            sender = row.pop("card") or row.pop("nickname")
            sender = sender or row.get("sender_number") or row.get("sender_uid")
            sent_at = int(row["sent_at"] or 0)
            messages.append(
                {
                    "conversation_id": f"{kind}:{key}",
                    "conversation_name": group_names.get(key) if kind == "group" else None,
                    "message_id": str(row["message_id"]),
                    "timestamp": sent_at,
                    "time": datetime.fromtimestamp(sent_at).astimezone().isoformat()
                    if sent_at
                    else None,
                    "sender": str(sender) if sender is not None else "unknown",
                    "sender_number": row.get("sender_number"),
                    "content": message_preview(body),
                    "content_metadata": message_metadata(
                        body,
                        member_names=member_names_by_group.get(key),
                    ),
                }
            )
        return {
            "synced_at": datetime.now().astimezone().isoformat(),
            "refresh_ms": round((time.monotonic() - started) * 1000),
            "count": len(messages),
            "page_limit": page.limit,
            "page_order": "chronological_oldest_to_newest",
            "pagination_direction": "backward_in_time",
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
            "window_start": datetime.fromtimestamp(page.cutoff).astimezone().isoformat(),
            "resolved_conversation": {
                "conversation_id": conversation_id,
                "conversation_name": resolved_name,
            }
            if resolved_name
            else None,
            "messages": messages,
        }

    def conversations(self, *, minutes: int = 24 * 60, limit: int = 100) -> dict:
        started = time.monotonic()
        connection = self._connection()
        try:
            rows = query_conversations(connection, minutes=minutes, limit=limit)
        finally:
            connection.close()
        names = self.group_names() if any(row["kind"] == "group" for row in rows) else {}
        conversations = []
        for row in rows:
            kind = str(row["kind"])
            key = str(row["conversation_key"] or "unknown")
            latest_at = int(row["latest_at"] or 0)
            conversations.append(
                {
                    "conversation_id": f"{kind}:{key}",
                    "conversation_name": names.get(key) if kind == "group" else None,
                    "kind": kind,
                    "latest_timestamp": latest_at,
                    "latest_time": datetime.fromtimestamp(latest_at).astimezone().isoformat()
                    if latest_at
                    else None,
                    "message_count": int(row["message_count"] or 0),
                }
            )
        return {
            "synced_at": datetime.now().astimezone().isoformat(),
            "refresh_ms": round((time.monotonic() - started) * 1000),
            "count": len(conversations),
            "conversations": conversations,
        }

    def find_conversations(
        self, query: str = "", *, minutes: int = 365 * 24 * 60, limit: int = 20
    ) -> dict:
        limit = max(1, min(int(limit), 100))
        active = self.conversations(minutes=minutes, limit=MAX_CONVERSATION_LIMIT)
        by_id = {item["conversation_id"]: item for item in active["conversations"]}
        for key, name in self.group_names().items():
            identifier = f"group:{key}"
            by_id.setdefault(
                identifier,
                {
                    "conversation_id": identifier,
                    "conversation_name": name,
                    "kind": "group",
                    "latest_timestamp": 0,
                    "latest_time": None,
                    "message_count": 0,
                },
            )

        requested = query.strip().casefold()

        def match_score(item: dict) -> int | None:
            if not requested:
                return 3
            identifier = item["conversation_id"].casefold()
            name = str(item.get("conversation_name") or "").casefold()
            if requested in {identifier, identifier.removeprefix("group:"), name}:
                return 0
            if name.startswith(requested):
                return 1
            if requested in name or requested in identifier:
                return 2
            return None

        ranked = [
            (score, item)
            for item in by_id.values()
            if (score := match_score(item)) is not None
        ]
        ranked.sort(
            key=lambda pair: (
                pair[0],
                -int(pair[1]["latest_timestamp"] or 0),
                str(pair[1].get("conversation_name") or ""),
                pair[1]["conversation_id"],
            )
        )
        matches = [item for _, item in ranked[:limit]]
        return {
            "synced_at": active["synced_at"],
            "query": query,
            "matched_count": len(ranked),
            "count": len(matches),
            "matches": matches,
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
