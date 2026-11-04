"""S1 M5：帶 hash 的 lock 檔（requirements*.txt）和 pyproject.toml 對得上。

Actions 一律 `pip install --require-hashes -r <lock 檔>`。pyproject.toml 改了下限、加了套件，
或 Dependabot 只改了其中一邊時，這裡會紅：照 README「相依套件」重產 lock 檔。這個測試不連網。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")


def _lock(name: str) -> dict[str, tuple[Version, int]]:
    """lock 檔 → {套件: (版本, hash 數)}。"""
    out: dict[str, tuple[Version, int]] = {}
    current: str | None = None
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        m = _PIN.match(line)
        if m:
            current = canonicalize_name(m[1])
            out[current] = (Version(m[2]), 0)
        elif current and line.strip().startswith("--hash=sha256:"):
            v, n = out[current]
            out[current] = (v, n + 1)
        elif line and not line.startswith((" ", "#")):
            current = None
    return out


def _direct(extra: str | None = None) -> list[Requirement]:
    reqs = list(PYPROJECT["project"]["dependencies"])
    if extra:
        reqs += PYPROJECT["project"]["optional-dependencies"][extra]
    return [Requirement(r) for r in reqs]


def _events_in() -> list[Requirement]:
    lines = (ROOT / "requirements-events.in").read_text(encoding="utf-8").splitlines()
    return [Requirement(x) for x in (s.split("#")[0].strip() for s in lines) if x and x[0] != "-"]


CASES = [
    ("requirements.txt", _direct()),
    ("requirements-dev.txt", _direct("dev")),
    ("requirements-events.txt", _events_in()),
]


@pytest.mark.parametrize(("name", "direct"), CASES, ids=[c[0] for c in CASES])
def test_lock_matches_pyproject(name, direct):
    lock = _lock(name)
    assert lock, f"{name} 是空的"
    for req in direct:
        key = canonicalize_name(req.name)
        assert key in lock, f"{name} 沒有 {req.name}：重產 lock 檔"
        version, _ = lock[key]
        assert req.specifier.contains(version, prereleases=True), (
            f"{name} 的 {req.name}=={version} 不符合 {req.specifier}：重產 lock 檔"
        )


@pytest.mark.parametrize("name", [c[0] for c in CASES])
def test_lock_every_pin_has_hash(name):
    for pkg, (version, hashes) in _lock(name).items():
        assert hashes > 0, f"{name} 的 {pkg}=={version} 沒有 --hash"


def test_events_lock_same_versions_as_main():
    """events.yml 每小時那次的套件版本和 build 一樣（requirements-events.in 的 -c）。"""
    main = _lock("requirements.txt")
    for pkg, (version, _) in _lock("requirements-events.txt").items():
        assert pkg in main and main[pkg][0] == version, f"{pkg}=={version} 和 requirements.txt 不同"
