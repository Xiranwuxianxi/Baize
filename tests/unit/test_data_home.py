"""个人数据和代码分开：默认放在用户数据目录；旧版本放在项目文件夹里的数据会被自动搬走，绝不覆盖已有数据。
每个测试都在临时目录里造一个「旧项目」，用子进程跑 config.py，不碰真实的项目文件夹。"""
import json
import os
import shutil
import subprocess
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")


def _project(tmp_path, with_data=True):
    proj = tmp_path / "proj"
    (proj / "backend").mkdir(parents=True)
    shutil.copy(os.path.join(BACKEND, "config.py"), proj / "backend" / "config.py")
    if with_data:
        (proj / "data").mkdir()
        (proj / "data" / "mac.db").write_bytes(b"my-database")
        (proj / "workspace" / "会话-1").mkdir(parents=True)
        (proj / "workspace" / "会话-1" / "notes.txt").write_text("我的文件", encoding="utf-8")
        (proj / ".env").write_text("MY_SECRET=abc\n", encoding="utf-8")
    return proj


def _load(proj, home, **env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("MAC_")}
    if home is not None:
        clean["MAC_HOME"] = str(home)
    clean.update({"PYTHONIOENCODING": "utf-8", **env})
    code = ("import json, config; print(json.dumps({'data': config.DATA_DIR, 'ws': config.LOCAL['workspace'], "
            "'migrated': config.MIGRATED, 'secret': __import__('os').environ.get('MY_SECRET')}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=proj / "backend", env=clean, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _app_homes(tmp_path):
    """Keep every platform's user data paths inside the test directory."""
    user = tmp_path / "user"
    appdata = tmp_path / "appdata"
    xdg = tmp_path / "xdg"
    env = {
        "HOME": str(user),
        "USERPROFILE": str(user),
        "APPDATA": str(appdata),
        "XDG_DATA_HOME": str(xdg),
    }
    if os.name == "nt":
        base, old_name, new_name = appdata, "MultiAgentsControl", "Baize"
    elif sys.platform == "darwin":
        base = user / "Library" / "Application Support"
        old_name, new_name = "MultiAgentsControl", "Baize"
    else:
        base, old_name, new_name = xdg, "multi-agents-control", "baize"
    return base / old_name, base / new_name, env


def test_new_install_keeps_data_out_of_the_project(tmp_path):
    proj, home = _project(tmp_path, with_data=False), tmp_path / "home"
    got = _load(proj, home)
    assert got["data"] == str(home / "data") and got["ws"] == str(home / "workspace")
    assert not (proj / "data").exists() and not (proj / "workspace").exists()


def test_old_data_in_the_project_is_moved_out(tmp_path):
    proj, home = _project(tmp_path), tmp_path / "home"
    got = _load(proj, home)
    assert (home / "data" / "mac.db").read_bytes() == b"my-database"
    assert (home / "workspace" / "会话-1" / "notes.txt").read_text(encoding="utf-8") == "我的文件"
    assert got["secret"] == "abc" and (home / ".env").exists()  # .env 也搬了，并且照样读到
    assert not (proj / "data").exists() and not (proj / "workspace").exists() and not (proj / ".env").exists()
    assert got["data"] == str(home / "data") and len(got["migrated"]) == 3


def test_existing_data_at_the_new_location_is_never_overwritten(tmp_path):
    proj, home = _project(tmp_path), tmp_path / "home"
    (home / "data").mkdir(parents=True)
    (home / "data" / "mac.db").write_bytes(b"newer-database")
    got = _load(proj, home)
    assert (home / "data" / "mac.db").read_bytes() == b"newer-database"  # 新位置的数据原封不动
    assert (proj / "data" / "mac.db").read_bytes() == b"my-database"     # 旧的也还在，没有丢
    assert got["data"] == str(home / "data")


def test_explicit_locations_are_respected(tmp_path):
    proj, home = _project(tmp_path), tmp_path / "home"
    got = _load(proj, home, MAC_DATA_DIR=str(tmp_path / "elsewhere"))
    assert got["data"] == str(tmp_path / "elsewhere") and got["migrated"] == []
    assert (proj / "data" / "mac.db").exists()  # 明确指定了位置：什么都不搬


def test_default_location_on_each_platform(monkeypatch):
    """三个系统各自约定的用户数据目录（不设 MAC_HOME 时）。"""
    import config
    monkeypatch.delenv("MAC_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(config.os, "name", "nt")
    monkeypatch.setenv("APPDATA", r"C:\Users\ada\AppData\Roaming")
    assert config._default_home() == os.path.join(r"C:\Users\ada\AppData\Roaming", "Baize")

    monkeypatch.setattr(config.os, "name", "posix")
    monkeypatch.setattr(config.sys, "platform", "darwin")
    assert config._default_home() == os.path.expanduser("~/Library/Application Support/Baize")

    monkeypatch.setattr(config.sys, "platform", "linux")
    assert config._default_home() == os.path.join(os.path.expanduser("~/.local/share"), "baize")
    monkeypatch.setenv("XDG_DATA_HOME", "/data/ada")
    assert config._default_home() == os.path.join("/data/ada", "baize")

    monkeypatch.setenv("MAC_HOME", "~/my-agents")  # 显式指定总是优先
    assert config._default_home() == os.path.abspath(os.path.expanduser("~/my-agents"))


def test_renamed_app_moves_old_data_home(tmp_path):
    """产品改名（MultiAgentsControl → 白泽 Baize）：旧数据目录整体搬到新名字下。"""
    proj = _project(tmp_path, with_data=False)
    legacy, home, env = _app_homes(tmp_path)
    (legacy / "data").mkdir(parents=True)
    (legacy / "data" / "mac.db").write_bytes(b"old-home-database")
    got = _load(proj, None, **env)
    assert got["data"] == str(home / "data")
    assert (home / "data" / "mac.db").read_bytes() == b"old-home-database"
    assert not legacy.exists()
    assert any("数据目录" in m for m in got["migrated"])


def test_renamed_home_never_overwrites_existing(tmp_path):
    """新旧两个数据目录都存在时：保留新的，旧的原样留在原地（什么都不丢）。"""
    proj = _project(tmp_path, with_data=False)
    legacy, home, env = _app_homes(tmp_path)
    (legacy / "data").mkdir(parents=True)
    (legacy / "data" / "mac.db").write_bytes(b"old")
    (home / "data").mkdir(parents=True)
    (home / "data" / "mac.db").write_bytes(b"new")
    got = _load(proj, None, **env)
    assert (home / "data" / "mac.db").read_bytes() == b"new"
    assert (legacy / "data" / "mac.db").read_bytes() == b"old"
    assert got["data"] == str(home / "data")
