import sqlite3
import time

from qqnt_export_macos.recent import query_recent


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


def test_recent_query_caps_limit():
    connection = sqlite3.connect(":memory:")
    _schema(connection, "group_msg_table")
    now = int(time.time())
    connection.executemany(
        "INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (index, index, "sender", index, now, "group", index, 1, "", "", 1, b"")
            for index in range(250)
        ],
    )

    assert len(query_recent(connection, minutes=1, limit=500)) == 200
