import os
import subprocess
from pathlib import Path

import pytest

from test_support.windows import bash_executable, bash_path, native_path


def test_bash_path_converts_windows_drive_and_separators():
    assert bash_path(r"C:\dir with spaces\a;$()&.sh") == "/c/dir with spaces/a;$()&.sh"


def test_bash_path_keeps_posix_path():
    assert bash_path(Path("/tmp/example")) == "/tmp/example"


def test_native_path_inverts_bash_drive_spelling_on_windows():
    assert native_path("/c/dir with spaces/x", windows=True) == "C:/dir with spaces/x"
    assert native_path("/d", windows=True) == "D:/"
    assert native_path("C:/already/native", windows=True) == "C:/already/native"
    assert native_path("/tmp/x", windows=True) == "/tmp/x"


def test_native_path_keeps_posix_path_off_windows():
    assert native_path("/c/x", windows=False) == "/c/x"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific Bash selection")
def test_bash_executable_prefers_git_bash_over_wsl_launcher():
    selected = Path(bash_executable())

    assert "windowsapps" not in str(selected).lower()
    assert selected.name.lower() in {"bash.exe", "bash"}
    assert "git" in str(selected).lower()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific Bash selection")
def test_bash_executable_derives_git_bash_from_git_install_tree(tmp_path, monkeypatch):
    """Git for Windows 装在非默认目录、git.exe 落在 ucrt64\\bin 时，也从 git 安装树找到 usr\\bin\\bash.exe。"""
    import test_support.windows as W

    git_root = tmp_path / "dev-software" / "Git"
    bash = git_root / "usr" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_bytes(b"")
    git = git_root / "ucrt64" / "bin" / "git.exe"
    git.parent.mkdir(parents=True)
    git.write_bytes(b"")
    for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(W.shutil, "which", lambda name, *a, **k: str(git) if name == "git" else None)

    assert Path(W.bash_executable()) == bash


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific Bash selection")
def test_git_bash_preserves_path_command_overrides(tmp_path):
    stub = tmp_path / "grep"
    stub.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    result = subprocess.run(
        [bash_executable(), "-c", "grep anything"],
        env=dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}"),
        capture_output=True, timeout=15,
    )
    assert result.returncode == 42, result.stderr
