# Contributing

Contributions are welcome, especially compatibility reports that contain no personal data.

Before submitting a pull request:

1. Run `python -m pytest`.
2. Run `python -m compileall -q src tests`.
3. Run a secret/path scan over the staged diff.
4. Confirm that no database, key, export, screenshot, account identifier, or local user path is included.
5. Explain the QQ and macOS versions tested without uploading proprietary binaries.

Changes to the QQNT_Export integration patch must remain compatible with its GPLv3 license and update the pinned commit when necessary.
