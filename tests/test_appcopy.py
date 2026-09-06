from pathlib import Path

import pytest

import qqnt_export_macos.appcopy as appcopy


def test_prepare_app_rejects_non_app_source(tmp_path: Path):
    source = tmp_path / "QQ"
    source.mkdir()
    with pytest.raises(FileNotFoundError):
        appcopy.prepare_app(tmp_path / "copy.app", source)


def test_prepare_app_runs_copy_sign_and_verify(tmp_path: Path, monkeypatch):
    source = tmp_path / "QQ.app"
    source.mkdir()
    destination = tmp_path / "work/QQ-adhoc.app"
    calls = []

    def fake_run(command, check):
        calls.append(command)
        if command[0] == "ditto":
            destination.mkdir(parents=True)

    monkeypatch.setattr(appcopy.subprocess, "run", fake_run)
    assert appcopy.prepare_app(destination, source) == destination.resolve()
    assert [command[0] for command in calls] == ["ditto", "codesign", "codesign"]
