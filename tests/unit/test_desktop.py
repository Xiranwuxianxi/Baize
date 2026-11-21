"""Frozen resource paths and the desktop server's parent-controlled lifecycle."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import httpx

import config

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_resources_use_the_bundle_without_changing_user_data(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("MAC_HOME", str(tmp_path / "personal"))
    assert config._resource_root() == str(tmp_path / "bundle")
    assert config._default_home() == str(tmp_path / "personal")


def test_desktop_server_chooses_a_port_and_stops_when_its_parent_closes(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MAC_")}
    env.update(MAC_HOME=str(tmp_path / "home"), MAC_HOST="127.0.0.1", PYTHONIOENCODING="utf-8")
    lines = queue.Queue()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "backend" / "desktop_entry.py")], cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    )

    def read_output():
        for line in proc.stdout:
            lines.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    captured = []
    try:
        deadline = time.monotonic() + 30
        while True:
            line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
            captured.append(line)
            if line.startswith("BAIZE_DESKTOP_READY "):
                ready = json.loads(line.split(" ", 1)[1])
                break
            assert time.monotonic() < deadline, "".join(captured)
        assert ready["host"] == "127.0.0.1" and 0 < ready["port"] <= 65535
        url = "http://127.0.0.1:%s/api/state" % ready["port"]
        deadline = time.monotonic() + 15
        while True:
            try:
                response = httpx.get(url, timeout=1, trust_env=False)
                assert response.status_code == 200
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "".join(captured)
                time.sleep(0.05)
        proc.stdin.close()
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if not proc.stdin.closed:
            proc.stdin.close()
        reader.join(timeout=5)
        proc.stdout.close()


def test_desktop_outputs_are_ignored_but_build_sources_are_trackable():
    generated = [".desktop-build/backend/server.exe", "release/Baize.exe", "desktop/node_modules/electron/index.js", "desktop/build.log"]
    sources = ["desktop/main.cjs", "desktop/backend.spec", "desktop/package-lock.json", ".github/workflows/desktop.yml"]
    ignored = subprocess.run(["git", "check-ignore", "--no-index", *generated, *sources], cwd=ROOT, capture_output=True, text=True)
    assert ignored.returncode == 0, ignored.stderr
    assert set(ignored.stdout.splitlines()) == set(generated)
