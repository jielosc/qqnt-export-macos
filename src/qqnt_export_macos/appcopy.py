"""Create a private ad-hoc-signed QQ copy without touching /Applications."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


DEFAULT_QQ_APP = Path("/Applications/QQ.app")


def _inside_applications(path: Path) -> bool:
    applications = Path("/Applications").resolve()
    return path == applications or applications in path.parents


def prepare_app(destination: Path, source: Path = DEFAULT_QQ_APP) -> Path:
    """Copy QQ with ditto and ad-hoc sign only the destination bundle."""
    os.umask(0o077)
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_dir() or source.suffix != ".app":
        raise FileNotFoundError(f"QQ app bundle not found: {source}")
    if destination.suffix != ".app":
        raise ValueError("destination must end in .app")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    if _inside_applications(destination):
        raise ValueError("destination must not be inside /Applications")
    if source == destination or source in destination.parents:
        raise ValueError("destination must not be inside the source app")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    subprocess.run(["ditto", str(source), str(destination)], check=True)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(destination)],
        check=True,
    )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(destination)],
        check=True,
    )
    for path in [destination, *destination.rglob("*")]:
        if path.is_symlink():
            continue
        path.chmod(path.stat().st_mode & ~0o077)
    return destination
