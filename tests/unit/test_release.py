"""发布相关的一致性检查：版本号只有一个来源，依赖版本有上限。"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def test_version_has_a_single_source():
    version = read("VERSION").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert json.loads(read("frontend", "package.json"))["version"] == version
    first = re.search(r"^## \[(\d+\.\d+\.\d+)\]", read("CHANGELOG.md"), re.M).group(1)
    assert first == version  # 最新一条发布记录和版本号一致
    import main
    assert main.VERSION == version and main.app.version == version


def test_direct_dependencies_have_upper_bounds():
    for line in read("backend", "requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if line:
            assert "<" in line, "依赖缺少版本上限：" + line


def test_lock_pins_every_package():
    for line in read("backend", "requirements.lock").splitlines():
        line = line.split("#")[0].strip()
        if line:
            assert "==" in line, "锁定文件里的包必须精确到版本：" + line
