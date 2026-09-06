from pathlib import Path

from qqnt_export_macos.exporter import write_config


def test_config_is_offline_and_private(tmp_path: Path):
    config = tmp_path / "export.toml"
    write_config(config, tmp_path / "plain", tmp_path / "nt_data", tmp_path / "out")
    body = config.read_text(encoding="utf-8")
    assert "offline = true" in body
    assert 'output_format = ["chatlab_json", "chatlab_jsonl", "html"]' in body
    assert config.stat().st_mode & 0o077 == 0
