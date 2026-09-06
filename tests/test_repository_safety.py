from pathlib import Path
import re


def test_repository_contains_no_local_user_or_account_hash():
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        re.compile("/" + "Users" + "/"),
        re.compile(r"nt_qq_[0-9a-f]{32}"),
    )
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in forbidden:
            assert not pattern.search(body), f"sensitive pattern in {path}"
