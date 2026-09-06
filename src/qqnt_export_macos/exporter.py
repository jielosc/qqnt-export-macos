"""Prepare and run the GPL-licensed QQNT_Export backend."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


QQNT_EXPORT_REPOSITORY = "https://github.com/Tealina28/QQNT_Export.git"
QQNT_EXPORT_COMMIT = "714d228dcd52f74b06bec91d4dba6ab856f16cd1"


def bootstrap_exporter(destination: Path, patch_file: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    subprocess.run(
        ["git", "clone", QQNT_EXPORT_REPOSITORY, str(destination)], check=True
    )
    subprocess.run(
        ["git", "checkout", QQNT_EXPORT_COMMIT], cwd=destination, check=True
    )
    subprocess.run(
        ["git", "apply", str(patch_file.resolve())], cwd=destination, check=True
    )
    subprocess.run(
        [sys.executable, "-m", "venv", str(destination / ".venv")], check=True
    )
    subprocess.run(
        [
            str(destination / ".venv/bin/python"),
            "-m",
            "pip",
            "install",
            "-r",
            str(destination / "requirements.txt"),
        ],
        check=True,
    )


def write_config(
    destination: Path,
    plaintext: Path,
    nt_data: Path,
    output: Path,
) -> None:
    """Write a private TOML config for the patched exporter."""
    os.umask(0o077)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    quote = lambda path: json.dumps(str(path.expanduser().resolve()))
    text = f"""db_path = {quote(plaintext)}
pic_path = {quote(nt_data / 'Pic')}
output_path = {quote(output)}

c2c_filters = []
group_filters = []
conversation_types = ["c2c", "group", "dataline"]
dataline_owner = "pc"
output_format = ["chatlab_json", "chatlab_jsonl", "html"]
stream_batch_size = 1000

copy_resources = true
avatar_path = {quote(nt_data / 'avatar')}
emoji_path = {quote(nt_data)}
embed_avatars = false
ptt_path = {quote(nt_data)}
silk_transcode = true
offline = true

[decrypt]
enabled = false
"""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    os.chmod(destination, 0o600)


def run_exporter(checkout: Path, config: Path) -> None:
    python = checkout.resolve() / ".venv/bin/python"
    if not python.is_file():
        raise FileNotFoundError(f"exporter virtual environment not found: {python}")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [str(python), "main.py", str(config.resolve())],
        cwd=checkout.resolve(),
        env=environment,
        check=True,
    )
