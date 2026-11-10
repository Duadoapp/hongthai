"""S1 L25（HD45）：`build.yml` 拆成 build／publish 兩個 job 之後的界線。不連網。

- build：拿來源與 AI 的 secrets，token 只能讀（沒有 `contents: write`、`pages`、`id-token`）
- publish：拿可寫的 token 與 Pages 的 OIDC token，不引用任何 `secrets.`、不裝套件、不跑 Python
- 每個 action 都釘完整 commit SHA（M6）
- 兩個 job 之間傳 `data` 分支變更的那兩段 shell，拿本機的 git repo 實際跑一遍：刪檔、二進位檔、
  檔名有空白與中文、build 期間 `events` 先推了同一個 `.jsonl`（`merge=union`）都要對
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
DOC = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
JOBS = DOC["jobs"]
_SHA = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")


def _step(job: str, name: str) -> dict:
    return next(s for s in JOBS[job]["steps"] if s.get("name", "").startswith(name))


def test_top_level_permissions_are_read_only():
    assert DOC["permissions"] == {"contents": "read"}
    assert DOC["concurrency"] == {"group": "build", "cancel-in-progress": False}
    assert set(JOBS) == {"build", "publish"}


def test_build_job_has_secrets_but_read_only_token():
    job = JOBS["build"]
    assert job["permissions"] == {"contents": "read"}
    assert "environment" not in job  # github-pages 環境（與它的保護規則、OIDC）只在 publish
    text = yaml.safe_dump(job)
    assert "secrets.ANTHROPIC_API_KEY" in text
    assert "git push" not in text and "push_data.sh" not in text
    assert "deploy-pages" not in text


def test_publish_job_has_no_secrets_and_runs_no_python():
    job = JOBS["publish"]
    assert job["needs"] == "build"
    assert job["permissions"] == {"contents": "write", "pages": "write", "id-token": "write"}
    assert job["environment"]["name"] == "github-pages"
    text = yaml.safe_dump(job, allow_unicode=True)
    assert "secrets." not in text  # GITHUB_TOKEN 由 checkout 預設帶，不用寫出來
    assert "vars." not in text
    assert "env" not in job
    for step in job["steps"]:
        run = step.get("run", "")
        assert not re.search(r"\b(python3?|pip3?|pytest)\b", run), step.get("name")
        assert "setup-python" not in step.get("uses", "")
        assert "PYTHONPATH" not in step.get("env", {})
    uses = [s["uses"].split("@")[0] for s in job["steps"] if "uses" in s]
    assert uses == ["actions/checkout", "actions/download-artifact", "actions/deploy-pages"]


def test_publish_keeps_old_conditions():
    # 原本「推 data 分支」是 if: always()；Pages 只在有 public/latest.json 時發布、排在推 data 之後
    job = JOBS["publish"]
    assert job["if"] == "always() && needs.build.outputs.packed == 'true'"
    names = [s.get("name", s.get("uses")) for s in job["steps"]]
    assert names.index("推 data 分支") < names.index("發布到 GitHub Pages")
    assert _step("publish", "發布到 GitHub Pages")["if"] == "needs.build.outputs.pages == 'true'"
    assert "if" not in _step("publish", "推 data 分支")
    assert _step("publish", "推 data 分支")["run"].strip() == "../tools/push_data.sh data"
    build = JOBS["build"]
    assert _step("build", "產生 latest.json")["continue-on-error"] is True
    assert _step("build", "產生 latest.json")["timeout-minutes"] == 45
    assert _step("build", "包 data 分支的變更")["if"] == "always()"
    assert _step("build", "流程失敗時標紅")["if"] == "steps.build.outcome != 'success'"
    assert build["steps"][0]["name"] == "記開始時間"
    assert build["timeout-minutes"] + job["timeout-minutes"] <= 70


def test_artifacts_expire_after_one_day():
    for name in ("上傳 data 變更", "上傳 Pages artifact"):
        assert _step("build", name)["with"]["retention-days"] == 1, name
    # artifact 只有 data 的 patch 與 public/：都是本來就要公開的
    assert _step("build", "上傳 data 變更")["with"]["path"] == "${{ runner.temp }}/data-changes"
    assert _step("build", "上傳 Pages artifact")["with"]["path"] == "public"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_full_sha(path: Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    uses = [s["uses"] for j in doc["jobs"].values() for s in j["steps"] if "uses" in s]
    assert uses
    for u in uses:
        assert _SHA.match(u), f"{path.name}: {u} 沒有釘完整 commit SHA"
    # 後面要註解版本（Dependabot 靠它更新）
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.search(r"uses:\s", line):
            assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", line), line


# ---- 兩段 shell 實際跑一遍 ----

GIT = shutil.which("git")
BOT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run([GIT, *BOT, *args], cwd=cwd, env=ENV, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}\n{r.stdout}\n{r.stderr}"
    return r.stdout.strip()


def _bash(cwd: Path, script: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script], cwd=cwd, env={**ENV, **env}, capture_output=True, text=True
    )


def _commit_all(cwd: Path, msg: str) -> None:
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "-m", msg)


def _remote(tmp: Path, *, with_data: bool) -> Path:
    """像 GitHub 的遠端：`main`（有 tools/push_data.sh）與 `data`；可以用 SHA 抓舊的 commit。"""
    bare = tmp / "remote.git"
    _git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(bare, "config", "uploadpack.allowAnySHA1InWant", "true")
    seed = tmp / "seed"
    _git(tmp, "init", "-q", "-b", "main", str(seed))
    (seed / "tools").mkdir()
    shutil.copy2(ROOT / "tools" / "push_data.sh", seed / "tools" / "push_data.sh")
    _commit_all(seed, "main")
    _git(seed, "push", "-q", str(bare), "main")
    if with_data:
        _git(seed, "checkout", "-q", "--orphan", "data")
        _git(seed, "rm", "-rfq", ".")
        (seed / "history" / "timing").mkdir(parents=True)
        (seed / "latest.json").write_text('{"generatedAt":"old","x":"' + "a" * 5000 + '"}\n')
        (seed / "history" / "old.json").write_text('{"old":true}\n')
        (seed / "history" / "keep.json").write_text('{"keep":true}\n')
        (seed / "history" / "timing" / ".gitattributes").write_text("*.jsonl merge=union\n")
        (seed / "history" / "timing" / "m.jsonl").write_text('{"n":1}\n')
        (seed / "og.png").write_bytes(bytes(range(256)) * 8)
        _commit_all(seed, "data 0")
        _git(seed, "push", "-q", str(bare), "data")
    return bare


def _checkout(tmp: Path, bare: Path, name: str) -> Path:
    """`actions/checkout` 預設的樣子：main、深度 1。"""
    repo = tmp / name
    _git(tmp, "clone", "-q", "--depth=1", "-b", "main", bare.as_uri(), str(repo))
    return repo


def _build_side(tmp: Path, bare: Path, with_data: bool) -> Path:
    repo = _checkout(tmp, bare, "build")
    if with_data:  # 同「取出 data 分支」那一步
        _git(repo, "fetch", "-q", "--depth=1", "origin", "data:data")
        _git(repo, "worktree", "add", "-q", "data", "data")
    else:
        _git(repo, "worktree", "add", "-q", "--orphan", "-b", "data", "data")
    data = repo / "data"
    (data / "history" / "timing").mkdir(parents=True, exist_ok=True)
    (data / "latest.json").write_text(
        '{"generatedAt":"new","x":"' + "b" * 5000 + '"}'
    )  # 結尾沒換行
    (data / "history" / "new.json").write_text('{"new":true}\n')
    (data / "history" / "有 空白.json").write_text('{"名":"值"}\r\n')
    with (data / "history" / "timing" / "m.jsonl").open("a") as f:
        f.write('{"n":"build"}\n')
    (data / "og.png").write_bytes(bytes(reversed(range(256))) * 9)
    if with_data:
        (data / "history" / "old.json").unlink()
    out = tmp / "artifact"
    r = _bash(
        repo,
        _step("build", "包 data 分支的變更")["run"],
        OUT=str(out),
        HAS_PAGES="true",
        GITHUB_OUTPUT=str(tmp / "out.txt"),
    )
    assert r.returncode == 0, r.stderr
    assert "packed=true" in (tmp / "out.txt").read_text()
    assert "pages=true" in (tmp / "out.txt").read_text()
    assert sorted(p.name for p in out.iterdir()) == ["base", "data.patch", "tree"]
    return out


def _publish_side(tmp: Path, bare: Path, artifact: Path) -> subprocess.CompletedProcess:
    repo = _checkout(tmp, bare, "publish")
    r = _bash(repo, _step("publish", "還原 data 分支的變更")["run"], IN=str(artifact))
    if r.returncode != 0:
        return r
    return _bash(repo / "data", "../tools/push_data.sh data")


def _files(bare: Path) -> dict[str, bytes]:
    names = _git(bare, "-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", "data")
    out = {}
    for n in names.splitlines():
        r = subprocess.run([GIT, "show", f"data:{n}"], cwd=bare, env=ENV, capture_output=True)
        out[n] = r.stdout
    return out


needs_git = pytest.mark.skipif(GIT is None or shutil.which("bash") is None, reason="要 git 與 bash")


@needs_git
def test_data_changes_roundtrip_while_events_pushed(tmp_path: Path):
    bare = _remote(tmp_path, with_data=True)
    artifact = _build_side(tmp_path, bare, with_data=True)
    # build 之後、publish 之前，events 推了 data：同一個 .jsonl 多一行、另外一個新檔
    ev = tmp_path / "events"
    _git(tmp_path, "clone", "-q", "-b", "data", bare.as_uri(), str(ev))
    with (ev / "history" / "timing" / "m.jsonl").open("a") as f:
        f.write('{"n":"events"}\n')
    (ev / "history" / "metar.json").write_text("{}\n")
    _commit_all(ev, "events")
    _git(ev, "push", "-q", "origin", "data")

    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode == 0, r.stdout + r.stderr
    files = _files(bare)
    assert "history/old.json" not in files  # 刪檔有帶過去
    assert files["history/keep.json"] == b'{"keep":true}\n'
    assert files["history/new.json"] == b'{"new":true}\n'
    assert files["history/有 空白.json"] == '{"名":"值"}\r\n'.encode()
    assert files["history/metar.json"] == b"{}\n"  # events 推的還在
    assert files["latest.json"] == b'{"generatedAt":"new","x":"' + b"b" * 5000 + b'"}'
    assert files["og.png"] == bytes(reversed(range(256))) * 9
    lines = files["history/timing/m.jsonl"].decode().splitlines()
    assert sorted(lines) == sorted(['{"n":1}', '{"n":"build"}', '{"n":"events"}'])
    assert _git(bare, "rev-list", "--count", "data") == "3"  # data 0、events、build（線性）


@needs_git
def test_data_changes_roundtrip_first_run_without_data_branch(tmp_path: Path):
    bare = _remote(tmp_path, with_data=False)
    artifact = _build_side(tmp_path, bare, with_data=False)
    assert (artifact / "base").read_text() == ""
    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode == 0, r.stdout + r.stderr
    files = _files(bare)
    assert set(files) == {
        "latest.json",
        "history/new.json",
        "history/有 空白.json",
        "history/timing/m.jsonl",
        "og.png",
    }


@needs_git
def test_no_changes_pushes_nothing(tmp_path: Path):
    bare = _remote(tmp_path, with_data=True)
    repo = _checkout(tmp_path, bare, "build")
    _git(repo, "fetch", "-q", "--depth=1", "origin", "data:data")
    _git(repo, "worktree", "add", "-q", "data", "data")
    out = tmp_path / "artifact"
    script = _step("build", "包 data 分支的變更")["run"]
    r = _bash(repo, script, OUT=str(out), HAS_PAGES="false", GITHUB_OUTPUT=str(tmp_path / "o"))
    assert r.returncode == 0, r.stderr
    assert (out / "data.patch").read_bytes() == b""
    before = _git(bare, "rev-parse", "data")
    r = _publish_side(tmp_path, bare, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "沒有新檔案" in r.stdout
    assert _git(bare, "rev-parse", "data") == before


@needs_git
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("base", "main\n"),
        ("base", "--upload-pack=x\n"),
        ("base", "x\n" + "0" * 40 + "\n"),
        ("tree", "0" * 39 + "\n"),
        ("tree", ""),
    ],
)
def test_publish_rejects_malformed_artifact(tmp_path: Path, name: str, value: str):
    bare = _remote(tmp_path, with_data=True)
    artifact = _build_side(tmp_path, bare, with_data=True)
    (artifact / name).write_text(value)
    before = _git(bare, "rev-parse", "data")
    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode != 0
    assert "格式不對" in r.stdout
    assert _git(bare, "rev-parse", "data") == before


@needs_git
def test_publish_rejects_patch_that_does_not_match_tree(tmp_path: Path):
    bare = _remote(tmp_path, with_data=True)
    artifact = _build_side(tmp_path, bare, with_data=True)
    patch = (artifact / "data.patch").read_bytes()
    (artifact / "data.patch").write_bytes(patch.replace(b'{"new":true}', b'{"new":fals}'))
    before = _git(bare, "rev-parse", "data")
    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode != 0
    assert _git(bare, "rev-parse", "data") == before
