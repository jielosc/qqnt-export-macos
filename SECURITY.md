# Security policy

## Sensitive data

Never attach or paste any of the following into an Issue, pull request, discussion, log, or chat:

- `.key` files or raw database keys
- QQ databases, WAL files, or database headers
- exported HTML, JSON, JSONL, media, avatars, or screenshots
- account hashes, UIDs, QQ numbers, contact names, or group names
- complete local filesystem paths if they contain identifying information

The default `.gitignore` excludes common sensitive artifacts, but it is not a substitute for reviewing `git status` before every commit.

## Reporting a vulnerability

Use GitHub's private security-advisory reporting feature if enabled. Otherwise, open a minimal Issue asking for a private contact channel without including exploit details or sensitive data.

## Design guarantees and non-guarantees

- The tool refuses to overwrite snapshots, plaintext directories, configs, or exporter checkouts.
- Keys are saved with mode `0600`; generated data uses `0700/0600` after `verify --privatize`.
- The key callback logs fingerprints and lengths, never key bytes.
- Decryption reads source snapshots without modifying them.
- The Agent bridge opens only a private mirror, never the live QQ database itself.
- MCP uses local standard I/O and exposes no send or mutation tools.
- MCP message content is disabled until `QQNT_ALLOW_CONTENT=1` is explicitly set.
- Offline HTML suppresses automatic remote media loads.
- The tool does not automatically delete sensitive data.
- It cannot guarantee compatibility with future QQ versions or recover corrupt databases.

The bridge does not make a cloud Agent local. Any content returned by an MCP tool becomes part of that Agent's context and may be processed outside the Mac. Use a local model when content must never leave the device, or restrict access with `QQNT_ALLOW_CONVERSATIONS`.
