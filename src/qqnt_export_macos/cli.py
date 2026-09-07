"""Command-line interface for the macOS QQNT export workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .appcopy import DEFAULT_QQ_APP, prepare_app
from .decrypt import DEFAULT_DATABASES, decrypt_directory
from .exporter import bootstrap_exporter, run_exporter, write_config
from .macho import locate_key_function
from .recent import DEFAULT_BRIDGE_CACHE, QQRecentReader, install_bridge_key
from .snapshot import (
    DEFAULT_QQ_ROOT,
    create_snapshot,
    discover_accounts,
    find_runtime_wrapper,
)
from .verify import privatize, verify_export


def _doctor() -> int:
    checks = {
        "macOS": sys.platform == "darwin",
        "Apple Silicon": platform.machine() == "arm64",
        "QQ": Path("/Applications/QQ.app").is_dir(),
        "lldb": shutil.which("lldb") is not None,
        "codesign": shutil.which("codesign") is not None,
        "git": shutil.which("git") is not None,
    }
    sip = subprocess.run(
        ["csrutil", "status"], capture_output=True, text=True, check=False
    )
    sip_text = (sip.stdout + sip.stderr).strip()
    checks["SIP enabled"] = "enabled" in sip_text.lower()
    for name, passed in checks.items():
        print(f"{'ok' if passed else 'FAIL':4}  {name}")

    app = Path("/Applications/QQ.app")
    if app.is_dir():
        signature = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(app)],
            capture_output=True,
            text=True,
            check=False,
        )
        print(
            f"{'ok' if signature.returncode == 0 else 'WARN':4}  "
            "QQ strict signature"
        )
    return 0 if all(checks.values()) else 1


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qqnt-export-macos",
        description="Local-first QQNT export workflow for Apple Silicon macOS",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="check platform, SIP, tools, and QQ")

    app = subparsers.add_parser(
        "prepare-app", help="copy and ad-hoc sign QQ outside /Applications"
    )
    app.add_argument("destination", type=Path)
    app.add_argument("--source", type=Path, default=DEFAULT_QQ_APP)

    snapshot = subparsers.add_parser("snapshot", help="copy stopped QQ data")
    snapshot.add_argument("destination", type=Path)
    snapshot.add_argument("--source", type=Path, default=DEFAULT_QQ_ROOT)
    snapshot.add_argument("--mode", choices=("full", "databases"), default="databases")

    accounts = subparsers.add_parser("accounts", help="list database directories")
    accounts.add_argument("root", type=Path)

    wrapper = subparsers.add_parser("find-wrapper", help="find active wrapper.node")
    wrapper.add_argument("qq_data_root", type=Path)
    wrapper.add_argument("--qq-app", type=Path)

    locate = subparsers.add_parser("locate", help="locate nt_sqlite3_key_v2")
    locate.add_argument("wrapper", type=Path)

    subparsers.add_parser(
        "lldb-script", help="print the bundled private key-capture script path"
    )

    decrypt = subparsers.add_parser("decrypt", help="decrypt a stopped nt_db snapshot")
    decrypt.add_argument("source", type=Path)
    decrypt.add_argument("destination", type=Path)
    decrypt.add_argument("key", type=Path, help="one .key file or a candidate directory")
    decrypt.add_argument(
        "--database",
        action="append",
        dest="databases",
        help="database name; repeat to override the default four",
    )

    bootstrap = subparsers.add_parser(
        "bootstrap-exporter", help="clone, patch, and install QQNT_Export"
    )
    bootstrap.add_argument("destination", type=Path)

    config = subparsers.add_parser("make-config", help="create an offline export config")
    config.add_argument("destination", type=Path)
    config.add_argument("--plaintext", type=Path, required=True)
    config.add_argument("--nt-data", type=Path, required=True)
    config.add_argument("--output", type=Path, required=True)

    export = subparsers.add_parser("export", help="run the patched QQNT_Export")
    export.add_argument("checkout", type=Path)
    export.add_argument("config", type=Path)

    verify = subparsers.add_parser("verify", help="validate formats and offline HTML")
    verify.add_argument("output", type=Path)
    verify.add_argument(
        "--privatize", action="store_true", help="set directories/files to 0700/0600"
    )

    for name, help_text in (
        ("bridge-status", "test a read-only live QQNT mirror"),
        ("recent", "read recent messages from a live QQNT mirror"),
    ):
        bridge = subparsers.add_parser(name, help=help_text)
        bridge.add_argument("--key", type=Path, required=True)
        bridge.add_argument("--source", type=Path, default=DEFAULT_QQ_ROOT)
        bridge.add_argument("--cache", type=Path, default=DEFAULT_BRIDGE_CACHE)
        bridge.add_argument("--account", help="optional nt_qq_… directory name")
        if name == "recent":
            bridge.add_argument("--minutes", type=int, default=10)
            bridge.add_argument("--limit", type=int, default=50)
            bridge.add_argument("--conversation")
            bridge.add_argument("--conversation-name")
            bridge.add_argument("--cursor")

    bridge_key = subparsers.add_parser(
        "install-bridge-key", help="validate and privately retain only the working key"
    )
    bridge_key.add_argument("candidates", type=Path)
    bridge_key.add_argument("destination", type=Path)
    bridge_key.add_argument("--source", type=Path, default=DEFAULT_QQ_ROOT)
    bridge_key.add_argument("--cache", type=Path, default=DEFAULT_BRIDGE_CACHE)
    bridge_key.add_argument("--account", help="optional nt_qq_… directory name")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.command == "doctor":
            return _doctor()
        if arguments.command == "prepare-app":
            print(prepare_app(arguments.destination, arguments.source))
            return 0
        if arguments.command == "snapshot":
            manifest = create_snapshot(
                arguments.destination, arguments.source, arguments.mode
            )
            print(f"snapshot complete: {len(manifest['databases'])} databases")
            return 0
        if arguments.command == "accounts":
            accounts = discover_accounts(arguments.root.resolve())
            for account in accounts:
                print(account)
            return 0 if accounts else 1
        if arguments.command == "find-wrapper":
            print(find_runtime_wrapper(arguments.qq_data_root, arguments.qq_app))
            return 0
        if arguments.command == "locate":
            location = locate_key_function(arguments.wrapper.resolve())
            print(f"0x{location.function_va:x}")
            return 0
        if arguments.command == "lldb-script":
            print(Path(__file__).with_name("lldb_capture.py").resolve())
            return 0
        if arguments.command == "decrypt":
            names = arguments.databases or list(DEFAULT_DATABASES)
            selected, results = decrypt_directory(
                arguments.source, arguments.destination, arguments.key, names
            )
            print(f"accepted key fingerprint: {_fingerprint(selected)}")
            for name, schema_count in results.items():
                print(f"decrypted {name}: {schema_count} schema objects")
            return 0
        if arguments.command == "bootstrap-exporter":
            patch = Path(__file__).with_name("qqnt-export.patch")
            bootstrap_exporter(arguments.destination, patch)
            return 0
        if arguments.command == "make-config":
            write_config(
                arguments.destination,
                arguments.plaintext,
                arguments.nt_data,
                arguments.output,
            )
            print(arguments.destination.resolve())
            return 0
        if arguments.command == "export":
            run_exporter(arguments.checkout, arguments.config)
            return 0
        if arguments.command == "verify":
            if arguments.privatize:
                privatize(arguments.output.resolve())
            summary, failures = verify_export(arguments.output)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            for failure in failures:
                print(f"ERROR: {failure}", file=sys.stderr)
            return 1 if failures else 0
        if arguments.command in {"bridge-status", "recent"}:
            reader = QQRecentReader(
                arguments.key,
                root=arguments.source,
                cache_dir=arguments.cache,
                account=arguments.account,
            )
            result = (
                reader.status()
                if arguments.command == "bridge-status"
                else reader.recent(
                    minutes=arguments.minutes,
                    limit=arguments.limit,
                    conversation_id=arguments.conversation,
                    conversation_name=arguments.conversation_name,
                    cursor=arguments.cursor,
                )
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if arguments.command == "install-bridge-key":
            fingerprint = install_bridge_key(
                arguments.candidates,
                arguments.destination,
                root=arguments.source,
                cache_dir=arguments.cache,
                account=arguments.account,
            )
            print(
                f"installed one validated key privately; fingerprint: {fingerprint}"
            )
            return 0
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
