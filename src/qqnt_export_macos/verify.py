"""Privacy-focused validation for exported QQ records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re


REMOTE_MEDIA = re.compile(
    r'<(?:img|audio|video|source)[^>]+src=["\']https?://', re.IGNORECASE
)
HTML_COMPLETION_MARKER = "window.__QQNT_EXPORT_META__"


def verify_export(root: Path) -> tuple[dict, list[str]]:
    root = root.resolve()
    failures = []
    json_files = sorted(
        path for path in root.rglob("*.json") if "resources" not in path.parts
    )
    jsonl_files = sorted(
        path for path in root.rglob("*.jsonl") if "resources" not in path.parts
    )
    html_files = sorted(
        path for path in root.rglob("*.html") if "resources" not in path.parts
    )
    messages = 0

    for path in json_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            messages += len(payload.get("messages", []))
        except Exception as exc:
            failures.append(f"invalid JSON {path.name}: {exc}")
    for path in jsonl_files:
        line_number = 0
        try:
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if line.strip():
                        json.loads(line)
        except Exception as exc:
            failures.append(f"invalid JSONL {path.name}:{line_number}: {exc}")
    for path in html_files:
        try:
            body = path.read_text(encoding="utf-8")
            if HTML_COMPLETION_MARKER not in body:
                failures.append(f"incomplete HTML {path.name}")
            if REMOTE_MEDIA.search(body):
                failures.append(f"remote auto-loaded media in {path.name}")
        except Exception as exc:
            failures.append(f"invalid HTML {path.name}: {exc}")

    readable_by_others = 0
    resources = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            failures.append(f"symbolic link is not allowed in output: {path.name}")
            continue
        if path.is_file():
            resources += int("resources" in path.parts)
            if path.stat().st_mode & 0o044:
                readable_by_others += 1
    if readable_by_others:
        failures.append(f"{readable_by_others} files are group/world-readable")

    summary = {
        "html": len(html_files),
        "json": len(json_files),
        "jsonl": len(jsonl_files),
        "messages": messages,
        "resources": resources,
        "group_or_world_readable_files": readable_by_others,
    }
    return summary, failures


def privatize(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
