# Changelog

## Unreleased

- Add `export-chatlab` for exact-day, recent-window, and explicit-range exports from the live read-only mirror.
- Preserve reply identifiers and embedded quoted-message context in ChatLab output.
- Keep ChatLab writes private and atomic while leaving existing parent directory permissions unchanged.

## 0.4.0 - 2026-09-07

- Add an implicitly discoverable `qq-messages` Agent Skill for QQ reading intents.
- Declare the hidden `qqnt-local` MCP server as the Skill's tool dependency.
- Route named groups, conversation discovery, diagnostics, and complete pagination.
- Keep message access read-only and prohibit silent Computer Use or UI fallback.

## 0.3.1 - 2026-09-07

- Add bilingual, intent-driven MCP server and tool descriptions for automatic routing.
- Publish parameter-level guidance for time windows, group names, and cursor pagination.
- Mark every MCP tool as local, read-only, non-destructive, idempotent, and closed-world.
- Keep all essential routing and no-UI-fallback rules in the first 512 instruction characters.
- Make global `AGENTS.md` routing unnecessary when the MCP server loads successfully.

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
