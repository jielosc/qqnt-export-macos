"""Create private, immutable-in-practice copies of QQNT data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Literal


DEFAULT_QQ_ROOT = (
    Path.home()
    / "Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ"
)


def qq_is_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "^/Applications/QQ.app/Contents/MacOS/QQ$"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _database_manifest(destination: Path) -> dict:
    entries = []
    for path in sorted(destination.rglob("*.db")):
        if path.is_file() and not path.is_symlink():
            entries.append(
                {
                    "path": str(path.relative_to(destination)),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return {"format": 1, "databases": entries}


def create_snapshot(
    destination: Path,
    source: Path = DEFAULT_QQ_ROOT,
    mode: Literal["full", "databases"] = "databases",
) -> dict:
    """Copy stopped QQ data into a new mode-0700 destination."""
    os.umask(0o077)
    if qq_is_running():
        raise RuntimeError("QQ is running; quit it completely before snapshotting")
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    if source == destination or source in destination.parents:
        raise ValueError("destination must not be inside the source")

    live_journals = [
        path
        for account in source.glob("nt_qq_*")
        for path in (account / "nt_db").glob("*.db-*")
        if path.name.endswith(("-wal", "-journal"))
        and path.is_file()
        and path.stat().st_size
    ]
    if live_journals:
        raise RuntimeError(
            f"found {len(live_journals)} non-empty database journals; "
            "wait for QQ to finish exiting"
        )

    destination.mkdir(mode=0o700, parents=True)
    if mode == "full":
        shutil.copytree(
            source,
            destination / "Library/Application Support/QQ",
            dirs_exist_ok=False,
            symlinks=True,
            ignore=shutil.ignore_patterns(".DS_Store"),
            copy_function=shutil.copyfile,
        )
    else:
        accounts = sorted(
            path for path in source.glob("nt_qq_*") if (path / "nt_db").is_dir()
        )
        if not accounts:
            raise RuntimeError("no nt_qq_*/nt_db account directories found")
        for account in accounts:
            shutil.copytree(
                account / "nt_db",
                destination / account.name / "nt_db",
                symlinks=True,
                ignore=shutil.ignore_patterns(".DS_Store"),
                copy_function=shutil.copyfile,
            )

    manifest = _database_manifest(destination)
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.chmod(manifest_path, 0o600)
    for path in destination.rglob("*"):
        if path.is_symlink():
            continue
        try:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        except OSError:
            pass
    return manifest


def discover_accounts(root: Path) -> list[Path]:
    return sorted(
        path / "nt_db"
        for path in root.glob("nt_qq_*")
        if (path / "nt_db/nt_msg.db").is_file()
    )


def find_runtime_wrapper(qq_data_root: Path, qq_app: Path | None = None) -> Path:
    """Prefer the active QQ hot-update wrapper, then fall back to the app bundle."""
    config = qq_data_root / "versions/config.json"
    if config.is_file():
        try:
            current = json.loads(config.read_text(encoding="utf-8")).get("curVersion")
        except (OSError, json.JSONDecodeError):
            current = None
        if current:
            candidate = (
                qq_data_root
                / "versions"
                / current
                / "QQUpdate.app/Contents/Resources/app/wrapper.node"
            )
            if candidate.is_file():
                return candidate
    if qq_app:
        candidates = sorted(qq_app.rglob("wrapper.node"))
        if candidates:
            return candidates[0]
    raise FileNotFoundError("could not find the active wrapper.node")
