import sqlite3
import time

import pytest

from qqnt_export_macos.recent import (
    QQRecentReader,
    query_conversations,
    query_group_names,
    query_recent,
    query_recent_page,
)


def _schema(connection, table):
    connection.execute(
        f"""CREATE TABLE {table} (
            [40001] INTEGER PRIMARY KEY, [40003] INTEGER, [40020] TEXT,
            [40033] INTEGER, [40050] INTEGER, [40021] TEXT,
            [40030] INTEGER, [40027] INTEGER, [40093] TEXT,
            [40090] TEXT, [40011] INTEGER, [40800] BLOB
        )"""
    )


def test_recent_query_filters_conversation_and_orders():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "c2c_msg_table")
    now = int(time.time())
    connection.executemany(
        "INSERT INTO c2c_msg_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "sender-a", 1, now - 20, "peer-a", 100, 10, "A", "", 1, b"one"),
            (2, 2, "sender-b", 2, now - 10, "peer-b", 200, 20, "B", "", 1, b"two"),
        ],
    )

    rows = query_recent(
        connection, minutes=1, limit=20, conversation_id="c2c:200"
    )

    assert [row["message_id"] for row in rows] == [2]
    assert rows[0]["conversation_key"] == "200"


def test_recent_query_caps_page_at_1000():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "group_msg_table")
    now = int(time.time())
    connection.executemany(
        "INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (index, index, "sender", index, now, "group", index, 1, "", "", 1, b"")
            for index in range(1250)
        ],
    )

    assert len(query_recent(connection, minutes=1, limit=5000)) == 1000


def test_recent_query_paginates_without_gaps_or_duplicates():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "group_msg_table")
    now = int(time.time())
    connection.executemany(
        "INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (index, index, "sender", index, now, "group", 42, 42, "", "", 1, b"")
            for index in range(5)
        ],
    )

    first = query_recent_page(connection, minutes=1, limit=2)
    second = query_recent_page(connection, minutes=1, limit=2, cursor=first.next_cursor)
    third = query_recent_page(connection, minutes=1, limit=2, cursor=second.next_cursor)

    assert [row["message_id"] for row in first.rows] == [4, 3]
    assert [row["message_id"] for row in second.rows] == [2, 1]
    assert [row["message_id"] for row in third.rows] == [0]
    assert first.has_more and second.has_more and not third.has_more
    assert third.next_cursor is None
    assert first.cutoff == second.cutoff == third.cutoff


def test_recent_query_rejects_invalid_cursor():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "group_msg_table")
    with pytest.raises(ValueError, match="invalid message cursor"):
        query_recent_page(connection, cursor="not-a-cursor")


def test_recent_cursor_is_bound_to_conversation():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "group_msg_table")
    now = int(time.time())
    connection.executemany(
        "INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (index, index, "sender", index, now, "group", 42, 42, "", "", 1, b"")
            for index in range(3)
        ],
    )
    first = query_recent_page(
        connection, minutes=1, limit=1, conversation_id="group:42"
    )

    with pytest.raises(ValueError, match="different conversation"):
        query_recent_page(
            connection,
            minutes=1,
            limit=1,
            conversation_id="group:43",
            cursor=first.next_cursor,
        )


def test_group_names_include_active_and_historical_groups():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE group_list ([60001] INTEGER, [60007] TEXT)")
    connection.execute(
        "CREATE TABLE group_detail_info_ver1 ([60001] INTEGER, [60007] TEXT)"
    )
    connection.executemany(
        "INSERT INTO group_list VALUES (?, ?)", [(1, "Current"), (2, "")]
    )
    connection.executemany(
        "INSERT INTO group_detail_info_ver1 VALUES (?, ?)",
        [(1, "Current"), (2, "Historical")],
    )

    assert query_group_names(connection) == {"1": "Current", "2": "Historical"}


def test_conversation_counts_cover_the_full_window():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "group_msg_table")
    now = int(time.time())
    connection.executemany(
        "INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (index, index, "sender", index, now, "group", group, group, "", "", 1, b"")
            for index, group in enumerate([1] * 250 + [2] * 75)
        ],
    )

    rows = query_conversations(connection, minutes=1, limit=10)

    assert [(row["conversation_key"], row["message_count"]) for row in rows] == [
        ("1", 250),
        ("2", 75),
    ]


def test_group_name_resolution_requires_unique_match():
    reader = object.__new__(QQRecentReader)
    reader.group_names = lambda: {"1": "Green Lab", "2": "Green Lab Alumni"}

    assert reader.resolve_group_name("Green Lab") == ("group:1", "Green Lab")
    with pytest.raises(ValueError, match="ambiguous"):
        reader.resolve_group_name("green")
    with pytest.raises(ValueError, match="no QQ group matches"):
        reader.resolve_group_name("missing")
    assert reader.resolve_group_name("alumni", {"group:2"}) == (
        "group:2",
        "Green Lab Alumni",
    )
    with pytest.raises(ValueError, match="no QQ group matches"):
        reader.resolve_group_name("group:1", {"group:2"})
