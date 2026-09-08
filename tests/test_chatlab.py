import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qqnt_export_macos.chatlab import build_chatlab_payload, write_chatlab_payload

from test_message_preview import _body, _field


def test_build_chatlab_payload_preserves_reply_relation():
    quoted = _field(45002, 1) + _field(45101, "原消息".encode())
    reply = _field(45002, 7) + _field(47416, 111) + _field(47423, quoted)
    text = _field(45002, 1) + _field(45101, "正文".encode())
    start = datetime(2026, 9, 7, tzinfo=timezone(timedelta(hours=8)))
    end = start + timedelta(days=1)
    payload = build_chatlab_payload(
        [
            {
                "message_id": 222,
                "sender_uid": "u_sender",
                "sender_number": 123,
                "sent_at": int(start.timestamp()),
                "nickname": "昵称",
                "card": "群名片",
                "body": _body(reply) + _body(text),
            }
        ],
        conversation_id="group:42",
        conversation_name="测试群",
        range_start=start,
        range_end=end,
        exported_at=1234,
    )

    assert payload["chatlab"] == {
        "version": "0.0.2",
        "exportedAt": 1234,
        "generator": "qqnt-export-macos",
    }
    assert payload["meta"]["name"] == "测试群"
    assert payload["meta"]["platform"] == "qq"
    assert payload["meta"]["type"] == "group"
    assert payload["meta"]["groupId"] == "42"
    assert "avatar" not in payload["members"][0]
    assert payload["messages"] == [
        {
            "platformMessageId": "222",
            "sender": "u_sender",
            "accountName": "昵称",
            "timestamp": int(start.timestamp()),
            "type": 25,
            "content": "正文",
            "groupNickname": "群名片",
            "replyToMessageId": "111",
            "replyContext": {
                "sender": None,
                "accountName": None,
                "timestamp": None,
                "content": "原消息",
            },
            "contentMetadata": {
                "mentions": [],
                "elements": [
                    {
                        "type": "reply",
                        "data": {
                            "referencedMessageId": "111",
                            "referencedMessageIdRef": None,
                            "referencedMessageSeq": None,
                            "senderUid": None,
                            "senderUin": None,
                            "senderName": None,
                            "timestamp": None,
                            "content": "原消息",
                        },
                    }
                ],
            },
        }
    ]


def test_build_chatlab_payload_resolves_reply_sequence_within_range():
    reply = _field(45002, 7) + _field(47402, 7)
    text = _field(45002, 1) + _field(45101, "回复".encode())
    start = datetime(2026, 9, 7, tzinfo=timezone.utc)
    payload = build_chatlab_payload(
        [
            {
                "message_id": 111,
                "sequence": 7,
                "sender_uid": "u1",
                "sent_at": int(start.timestamp()),
                "nickname": "甲",
                "card": "",
                "body": _body(text),
            },
            {
                "message_id": 222,
                "sequence": 8,
                "sender_uid": "u2",
                "sent_at": int(start.timestamp()) + 1,
                "nickname": "乙",
                "card": "",
                "body": _body(reply) + _body(text),
            },
        ],
        conversation_id="group:42",
        conversation_name="测试群",
        range_start=start,
        range_end=start + timedelta(days=1),
    )

    assert payload["messages"][1]["replyToMessageId"] == "111"


def test_write_chatlab_payload_is_private_and_atomic(tmp_path: Path):
    destination = tmp_path / "exports" / "day.json"
    write_chatlab_payload(destination, {"messages": []})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"messages": []}
    assert destination.stat().st_mode & 0o077 == 0


def test_write_chatlab_payload_does_not_rechmod_existing_parent(tmp_path: Path):
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)

    write_chatlab_payload(parent / "day.json", {"messages": []})

    assert parent.stat().st_mode & 0o777 == 0o755
