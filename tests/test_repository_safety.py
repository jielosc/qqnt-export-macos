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


def test_bundled_qq_skill_is_implicitly_discoverable_and_depends_on_mcp():
    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills" / "qq-messages" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    manifest = (root / "skills" / "qq-messages" / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )

    assert skill.startswith("---\nname: qq-messages\n")
    assert "qq_recent_messages" in skill
    assert 'value: "qqnt-local"' in manifest
    assert "allow_implicit_invocation: true" in manifest
