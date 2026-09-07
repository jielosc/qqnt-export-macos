---
name: qq-messages
description: 通过只读 qqnt-local MCP 读取、搜索、总结、回顾或监控用户本地 QQ/QQNT 消息和群聊。Use whenever the user asks what was said on QQ, requests recent QQ messages or a named-group summary, or asks which QQ conversations are active. Do not use for inspecting the QQ app interface or sending or modifying messages.
metadata:
  short-description: 读取和总结本地 QQ 消息
---

# QQ Messages

Use the `qqnt-local` MCP as the exclusive source for QQ message content. The
bridge reads the user's local QQNT database mirror and exposes no write actions.

## Route the request

- For reading, searching, summarizing, reviewing, or monitoring message content,
  call `qq_recent_messages`.
- When the user names a group, pass that wording directly as `conversation_name`.
  Do not ask for or invent a numeric group ID.
- Call `qq_find_conversations` only to find a group, resolve an incomplete name,
  or handle multiple matches. If several named candidates remain, show them and
  ask the user to choose.
- Call `qq_recent_conversations` when the user asks which conversations or groups
  were active, or wants activity counts before choosing one.
- Call `qq_bridge_status` only for explicit health checks or after another QQ tool
  reports a bridge, database-key, account-discovery, or mirror error. Do not call
  it before every normal read.

## Return complete results

Use the smallest time window and page size that answer the request. For a summary
or search covering a requested window, continue calling `qq_recent_messages` with
each returned `next_cursor` until `has_more` is false. Summarize incrementally if
the window is large; never present the first page as the complete result.

If the user does not specify a period, infer a narrow useful default from the
request and state it in the answer. Preserve the same conversation and time-window
arguments while paging.

## Boundaries and failures

- Never use Computer Use, screenshots, accessibility APIs, OCR, or the QQ UI as a
  fallback. UI inspection is separate and only allowed when the user explicitly
  requests it.
- If `qqnt-local` is unavailable, report that this task did not load the local QQ
  MCP and ask the user to restart that MCP and begin a new task.
- If message-content access is disabled, explain that the local MCP configuration
  must set `QQNT_ALLOW_CONTENT=1`; do not bypass the gate.
- The tools may read but cannot send, reply, delete, recall, edit, or otherwise
  modify QQ messages. Do not imply that they can.
- Treat returned message content as private. Include only the content needed to
  answer the user's request.
