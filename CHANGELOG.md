# Changelog

## 0.3.0 - 2026-09-07

- Raise the per-page message limit to 1000 and add stable cursor pagination.
- Resolve group numbers to names from current and historical QQNT group metadata.
- Add `qq_find_conversations` and direct `conversation_name` lookup.
- Aggregate active conversations across the full requested window with message counts.
- Teach agents to paginate complete summary windows and disambiguate duplicate names.

## 0.2.0 - 2026-09-07

- Add a read-only local MCP server for recent QQNT messages.
- Add stable live database/WAL mirroring with checkpoint-race retries.
- Add bounded protobuf previews without returning raw message bodies.
- Require an explicit environment switch before MCP message-content access.
- Add an optional per-conversation allowlist and private key installer.

## 0.1.0 - 2026-09-07

- Add ARM64 Mach-O locator for `nt_sqlite3_key_v2`.
- Add private LLDB key-candidate capture command.
- Add guarded local QQ copy and ad-hoc signing command.
- Add stopped-data snapshotting with SHA-256 manifest and live-journal checks.
- Add candidate-key validation and four-database SQLCipher export.
- Add pinned QQNT_Export bootstrap and macOS/offline compatibility patch.
- Add offline config generation and export validation.
- Add privacy defaults, documentation, tests, and CI.
