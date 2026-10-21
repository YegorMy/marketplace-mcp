import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hermes_installer", ROOT / "scripts/configure-hermes-mcp.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_config_preserves_settings_and_backup_and_is_idempotent(tmp_path):
    path = tmp_path / "config.yaml"
    original = "# Keep a backup of this comment.\nmodel: test\nmcp_servers:\n  other:\n    url: https://example.invalid/mcp\n"
    path.write_text(original, encoding="utf-8-sig")
    project = str(tmp_path / "магазин's project")
    uv_bin = str(tmp_path / "tools with spaces" / "uv.exe")
    name = "shop's server"
    assert installer.configure(path, project, uv_bin, name)
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert config["model"] == "test"
    assert config["mcp_servers"]["other"] == {"url": "https://example.invalid/mcp"}
    assert config["mcp_servers"][name] == {
        "command": uv_bin,
        "args": ["run", "--project", project, "marketplaces-mcp"],
        "connect_timeout": 60, "enabled": True,
    }
    backup = path.with_name("config.yaml.bak")
    assert backup.read_text(encoding="utf-8-sig") == original
    assert installer.configure(path, project, uv_bin, name) is False
    assert backup.read_text(encoding="utf-8-sig") == original


@pytest.mark.parametrize("content", ["- invalid\n", "mcp_servers: []\n", "mcp_servers: value\n", "key: [\n"])
def test_invalid_config_is_not_changed(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError)):
        installer.configure(path, "project", "uv", "marketplaces")
    assert path.read_text(encoding="utf-8") == content
    assert not path.with_name("config.yaml.bak").exists()


def test_atomic_replace_failure_preserves_config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("model: original\n", encoding="utf-8")
    def failed_replace(*args):
        raise OSError("fixture replace failure")
    monkeypatch.setattr(installer.os, "replace", failed_replace)
    with pytest.raises(OSError, match="fixture replace failure"):
        installer.configure(path, "project", "uv", "marketplaces")
    assert path.read_text(encoding="utf-8") == "model: original\n"
    assert not list(tmp_path.glob(".marketplaces-mcp-*"))


@pytest.mark.parametrize("content", ["", "mcp_servers: null\n"])
def test_empty_config_is_supported(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    assert installer.configure(path, "project", "uv", "marketplaces")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["mcp_servers"]["marketplaces"]["enabled"]


def test_missing_config_is_not_created(tmp_path):
    path = tmp_path / "config.yaml"
    with pytest.raises(ValueError, match="Run Hermes setup first"):
        installer.configure(path, "project", "uv", "marketplaces")
    assert not path.exists()


def test_platform_config_paths_and_hermes_home(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local AppData"))
    monkeypatch.setattr(installer.sys, "platform", "win32")
    assert installer.config_path() == tmp_path / "Local AppData" / "hermes" / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "custom profile"))
    assert installer.config_path() == tmp_path / "custom profile" / "config.yaml"
    monkeypatch.delenv("HERMES_HOME")
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    assert installer.config_path() == Path.home() / ".hermes" / "config.yaml"


@pytest.mark.parametrize("shell", ["bash", "powershell.exe", "pwsh.exe"])
@pytest.mark.parametrize("failure", ["", "sync", "configure", "test"])
def test_installers_offline_from_another_directory(tmp_path, shell, failure):
    if (shell == "bash") == (sys.platform == "win32"):
        pytest.skip("Use the native shell on each platform")
    executable = shutil.which(shell)
    if not executable:
        pytest.fail(f"Required native installer test shell is missing: {shell}")

    project = tmp_path / "shop's project with spaces"
    shutil.copytree(ROOT / "scripts", project / "scripts")
    (project / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    config_dir = tmp_path / "Hermes profile"
    config_dir.mkdir()
    config = config_dir / "config.yaml"
    config.write_text("model: fixture\n", encoding="utf-8")
    if failure == "configure":
        config.write_text("mcp_servers: []\n", encoding="utf-8")
    original = config.read_bytes()
    log = tmp_path / "calls.jsonl"
    runner = tmp_path / "record.py"
    runner.write_text(
        "import json,os,subprocess,sys\n"
        "tool,*args=sys.argv[1:]\n"
        "with open(os.environ['INSTALLER_TEST_LOG'],'a',encoding='utf-8') as f:\n"
        " f.write(json.dumps([tool,*args])+'\\n')\n"
        "if tool=='uv' and args[0]=='sync':\n"
        " sys.exit(7 if os.environ['INSTALLER_TEST_FAILURE']=='sync' else 0)\n"
        "if tool=='uv':\n"
        " sys.exit(subprocess.call([sys.executable,*args[args.index('python')+1:]]))\n"
        "sys.exit(9 if os.environ['INSTALLER_TEST_FAILURE']=='test' else 0)\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "tools with spaces"
    bin_dir.mkdir()
    for tool in ("uv", "hermes"):
        if sys.platform == "win32":
            launcher = bin_dir / f"{tool}.cmd"
            launcher.write_text(
                f'@"%INSTALLER_TEST_PYTHON%" "%INSTALLER_TEST_RUNNER%" {tool} %*\n@exit /b %errorlevel%\n',
                encoding="ascii",
            )
        else:
            launcher = bin_dir / tool
            launcher.write_text(
                f'#!/bin/sh\nexec "$INSTALLER_TEST_PYTHON" "$INSTALLER_TEST_RUNNER" {tool} "$@"\n',
                encoding="ascii",
            )
            launcher.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "HERMES_HOME": str(config_dir), "INSTALLER_TEST_LOG": str(log),
           "INSTALLER_TEST_PYTHON": sys.executable, "INSTALLER_TEST_RUNNER": str(runner),
           "INSTALLER_TEST_FAILURE": failure}
    name = "shop's server"
    if shell == "bash":
        env.update(PROJECT_DIR=str(project), SERVER_NAME=name, UV_BIN=str(bin_dir / "uv"))
        command = [executable, str(project / "scripts/install-hermes-mcp.sh")]
    else:
        command = [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(project / "scripts/install-hermes-mcp.ps1"), "-ServerName", name,
                   "-UvBin", str(bin_dir / "uv.cmd")]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, timeout=40)
    if not log.exists():
        pytest.fail(f"Installer exited {result.returncode} before calling uv:\n"
                    + result.stdout.decode(errors="replace")
                    + result.stderr.decode(errors="replace"))
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0] == ["uv", "sync", "--frozen", "--project", str(project)]
    if failure == "sync":
        assert result.returncode != 0 and len(calls) == 1
        assert config.read_bytes() == original
    elif failure == "configure":
        assert result.returncode != 0 and len(calls) == 2
        assert config.read_bytes() == original
    else:
        assert calls[-1] == ["hermes", "mcp", "test", name]
        assert (result.returncode == 0) == (failure == ""), (result.stdout, result.stderr)
        entry = yaml.safe_load(config.read_text(encoding="utf-8"))["mcp_servers"][name]
        assert entry["args"] == ["run", "--project", str(project), "marketplaces-mcp"]
        assert Path(entry["command"]).parent == bin_dir
        assert yaml.safe_load(config.read_text(encoding="utf-8"))["model"] == "fixture"
