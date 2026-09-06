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
- Offline HTML suppresses automatic remote media loads.
- The tool does not automatically delete sensitive data.
- It cannot guarantee compatibility with future QQ versions or recover corrupt databases.
