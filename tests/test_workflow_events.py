"""HD51：`events.yml` 比照 HD45 拆成 collect／publish 兩個 job 之後的界線。不連網。

- collect：拿來源的 secrets，token 只能讀（沒有 `contents: write`）
- publish：拿可寫的 token，不引用任何 `secrets.`、不裝套件、不跑 Python
- 沒有變更就不包、publish 不起來；觸發方式、手動輸入、各步驟的 `if:` 照舊
- 打包與還原那兩段 shell 拿本機的 git repo 實際跑一遍（git 的輔助函式用 `test_workflow_build` 的）

action 釘完整 commit SHA 的檢查在 `test_workflow_build.test_actions_are_pinned_to_full_sha`
（四支 workflow 都看）。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import test_workflow_build as wb
import yaml

ROOT = wb.ROOT
DOC = yaml.safe_load((ROOT / ".github" / "workflows" / "events.yml").read_text(encoding="utf-8"))
ON = DOC[True]  # YAML 1.1 把 `on` 讀成 True
JOBS = DOC["jobs"]
DISPATCH = "github.event_name == 'workflow_dispatch'"


def _step(job: str, name: str) -> dict:
    return next(s for s in JOBS[job]["steps"] if s.get("name", "").startswith(name))


def test_top_level_permissions_are_read_only():
    assert DOC["permissions"] == {"contents": "read"}
    assert DOC["concurrency"] == {"group": "events", "cancel-in-progress": False}
    assert list(JOBS) == ["collect", "publish"]
    for job in JOBS.values():  # concurrency 掛在整個 run，不是各 job 自己一組
        assert "concurrency" not in job


def test_triggers_and_inputs_unchanged():
    assert ON["schedule"] == [{"cron": "7 * * * *"}]
    inputs = ON["workflow_dispatch"]["inputs"]
    assert {k: v["type"] for k, v in inputs.items()} == {
        "trigger": "choice",
        "backfill": "boolean",
        "backfill-tracks": "boolean",
        "backfill-metar": "boolean",
        "backfill-flights": "boolean",
        "backfill-openmeteo": "string",
        "wn3-archive": "boolean",
    }
    assert inputs["trigger"]["options"] == ["manual", "cloudflare"]
    assert inputs["trigger"]["default"] == "manual"
    assert all(v["default"] is False for v in inputs.values() if v["type"] == "boolean")
    assert inputs["backfill-openmeteo"]["default"] == ""


def test_collect_job_has_secrets_but_read_only_token():
    job = JOBS["collect"]
    assert job["permissions"] == {"contents": "read"}
    assert "environment" not in job
    assert job["timeout-minutes"] == 90
    text = yaml.safe_dump(job, allow_unicode=True)
    assert set(re.findall(r"secrets\.([A-Z_]+)", text)) == {
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CLOUD_PROJECT",
        "CWA_API_KEY",
        "TDX_CLIENT_ID",
        "TDX_CLIENT_SECRET",
    }
    assert "git push" not in text and "push_data.sh" not in text


def test_collect_steps_keep_their_conditions():
    steps = JOBS["collect"]["steps"]
    by_if = {s["name"]: s.get("if") for s in steps if "name" in s}
    assert by_if == {
        "裝套件": f"!({DISPATCH} && inputs.backfill-tracks)",
        "裝套件（backfill-tracks）": f"{DISPATCH} && inputs.backfill-tracks",
        "取出 data 分支": None,
        "搬過去的報（手動、backfill）": f"{DISPATCH} && inputs.backfill",
        "補颱風路徑（手動、backfill-tracks）": f"{DISPATCH} && inputs.backfill-tracks",
        "補 METAR 缺口（手動、backfill-metar）": f"{DISPATCH} && inputs.backfill-metar",
        "補香港航班（手動、backfill-flights）": f"{DISPATCH} && inputs.backfill-flights",
        "回補 Open-Meteo 新模式（手動、backfill-openmeteo）": (
            f"{DISPATCH} && inputs.backfill-openmeteo != ''"
        ),
        "每小時 METAR、颱風現報與航班": None,
        "WeatherNext 3 搬家（每天 00Z 那次、或手動 wn3-archive）": None,
        # 原本「推 data 分支」沒有 if：前面失敗就不推。打包也一樣
        "包 data 分支的變更": None,
        "上傳 data 變更（artifact，留 1 天）": "steps.pack.outputs.packed == 'true'",
    }
    assert not any(s.get("continue-on-error") for s in steps)
    # 會改 data/ 的步驟都在打包之前；打包之後只有上傳
    names = [s.get("name", s.get("uses")) for s in steps]
    assert names[-2:] == ["包 data 分支的變更", "上傳 data 變更（artifact，留 1 天）"]
    runs = [s["run"] for s in steps if "hongthai.events" in s.get("run", "")]
    assert len(runs) == 7 and all("--archive data" in r for r in runs)


def test_only_artifact_is_the_data_patch_and_expires_after_one_day():
    uploads = [s for s in JOBS["collect"]["steps"] if "upload" in s.get("uses", "")]
    assert len(uploads) == 1
    assert uploads[0]["with"] == {
        "name": "data-changes",
        "path": "${{ runner.temp }}/data-changes",
        "if-no-files-found": "error",
        "retention-days": 1,
    }
    assert _step("collect", "包 data 分支的變更")["env"] == {
        "OUT": "${{ runner.temp }}/data-changes"
    }


def test_publish_job_has_no_secrets_and_runs_no_python():
    job = JOBS["publish"]
    assert job["needs"] == "collect"
    # 沒有 always()：collect 失敗就不推（原本失敗的步驟之後「推 data 分支」不會跑）；
    # 沒有變更也不起來
    assert job["if"] == "needs.collect.outputs.packed == 'true'"
    assert job["permissions"] == {"contents": "write"}
    assert "environment" not in job
    assert JOBS["collect"]["outputs"] == {"packed": "${{ steps.pack.outputs.packed }}"}
    text = yaml.safe_dump(job, allow_unicode=True)
    assert "secrets." not in text  # GITHUB_TOKEN 由 checkout 預設帶，不用寫出來
    assert "vars." not in text
    assert "env" not in job
    for step in job["steps"]:
        run = step.get("run", "")
        assert not re.search(r"\b(python3?|pip3?|pytest)\b", run), step.get("name")
        assert "setup-python" not in step.get("uses", "")
        assert "PYTHONPATH" not in step.get("env", {})
        assert "if" not in step and "continue-on-error" not in step
    uses = [s["uses"].split("@")[0] for s in job["steps"] if "uses" in s]
    assert uses == ["actions/checkout", "actions/download-artifact"]
    assert _step("publish", "推 data 分支")["run"].strip() == "../tools/push_data.sh events"
    assert job["timeout-minutes"] <= 10


def test_same_action_versions_as_build():
    def pins(doc: dict) -> dict[str, str]:
        uses = [s["uses"] for j in doc["jobs"].values() for s in j["steps"] if "uses" in s]
        return dict(u.split("@") for u in uses)

    build = pins(wb.DOC)
    for name, sha in pins(DOC).items():
        assert build[name] == sha, name


# ---- 兩段 shell 實際跑一遍 ----


def _collect_side(tmp: Path, bare: Path, *, change: bool) -> tuple[Path, str]:
    repo = wb._checkout(tmp, bare, "collect")
    wb._git(repo, "fetch", "-q", "--depth=1", "origin", "data:data")  # 同「取出 data 分支」
    wb._git(repo, "worktree", "add", "-q", "data", "data")
    data = repo / "data"
    if change:
        ev = data / "history" / "events" / "29W"
        (ev / "metar").mkdir(parents=True)
        (ev / "metar" / "2026-11-13.jsonl").write_text('{"icao":"RCTP"}\n')
        (ev / "wn3 有空白.json").write_text('{"名":"值"}')  # 結尾沒換行
        with (data / "history" / "timing" / "m.jsonl").open("a") as f:
            f.write('{"n":"events"}\n')
        (data / "og.png").write_bytes(bytes(reversed(range(256))) * 9)
        (data / "history" / "old.json").unlink()
    out = tmp / "artifact"
    r = wb._bash(
        repo,
        _step("collect", "包 data 分支的變更")["run"],
        OUT=str(out),
        GITHUB_OUTPUT=str(tmp / "out.txt"),
    )
    assert r.returncode == 0, r.stderr
    return out, r.stdout + (tmp / "out.txt").read_text()


def _publish_side(tmp: Path, bare: Path, artifact: Path) -> subprocess.CompletedProcess:
    repo = wb._checkout(tmp, bare, "publish")
    r = wb._bash(repo, _step("publish", "還原 data 分支的變更")["run"], IN=str(artifact))
    if r.returncode != 0:
        return r
    return wb._bash(repo / "data", _step("publish", "推 data 分支")["run"])


@wb.needs_git
def test_events_changes_roundtrip_while_build_pushed(tmp_path: Path):
    bare = wb._remote(tmp_path, with_data=True)
    artifact, out = _collect_side(tmp_path, bare, change=True)
    assert "packed=true" in out
    assert sorted(p.name for p in artifact.iterdir()) == ["base", "data.patch", "tree"]
    # collect 之後、publish 之前，build 推了 data：同一個 .jsonl 多一行、latest.json 換新
    b = tmp_path / "b"
    wb._git(tmp_path, "clone", "-q", "-b", "data", bare.as_uri(), str(b))
    with (b / "history" / "timing" / "m.jsonl").open("a") as f:
        f.write('{"n":"build"}\n')
    (b / "latest.json").write_text('{"generatedAt":"new"}\n')
    wb._commit_all(b, "data: x")
    wb._git(b, "push", "-q", "origin", "data")

    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode == 0, r.stdout + r.stderr
    files = wb._files(bare)
    assert "history/old.json" not in files
    assert files["history/events/29W/metar/2026-11-13.jsonl"] == b'{"icao":"RCTP"}\n'
    assert files["history/events/29W/wn3 有空白.json"] == '{"名":"值"}'.encode()
    assert files["og.png"] == bytes(reversed(range(256))) * 9
    assert files["latest.json"] == b'{"generatedAt":"new"}\n'  # build 推的還在
    lines = files["history/timing/m.jsonl"].decode().splitlines()
    assert sorted(lines) == sorted(['{"n":1}', '{"n":"events"}', '{"n":"build"}'])
    assert wb._git(bare, "rev-list", "--count", "data") == "3"  # data 0、build、events（線性）
    # 一次 run 一個 commit，訊息和以前一樣是 `events: <UTC 時間>`
    assert re.fullmatch(
        r"events: \d{4}-\d\d-\d\dT\d\d:\d\dZ", wb._git(bare, "log", "-1", "--format=%s", "data")
    )


@wb.needs_git
def test_no_changes_packs_nothing(tmp_path: Path):
    bare = wb._remote(tmp_path, with_data=True)
    artifact, out = _collect_side(tmp_path, bare, change=False)
    assert "沒有新檔案" in out
    assert "packed=false" in out and "packed=true" not in out
    assert not artifact.exists()  # 沒有東西可上傳；publish 的 if 不成立


@wb.needs_git
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("base", ""),  # events 一定有 data 分支，不收空的 base
        ("base", "main\n"),
        ("base", "--upload-pack=x\n"),
        ("base", "x\n" + "0" * 40 + "\n"),
        ("tree", "0" * 39 + "\n"),
        ("tree", ""),
    ],
)
def test_publish_rejects_malformed_artifact(tmp_path: Path, name: str, value: str):
    bare = wb._remote(tmp_path, with_data=True)
    artifact, _ = _collect_side(tmp_path, bare, change=True)
    (artifact / name).write_text(value)
    before = wb._git(bare, "rev-parse", "data")
    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode != 0
    assert "格式不對" in r.stdout
    assert wb._git(bare, "rev-parse", "data") == before


@wb.needs_git
def test_publish_rejects_patch_that_does_not_match_tree(tmp_path: Path):
    bare = wb._remote(tmp_path, with_data=True)
    artifact, _ = _collect_side(tmp_path, bare, change=True)
    patch = (artifact / "data.patch").read_bytes()
    assert b'{"icao":"RCTP"}' in patch
    (artifact / "data.patch").write_bytes(patch.replace(b'{"icao":"RCTP"}', b'{"icao":"XXXX"}'))
    before = wb._git(bare, "rev-parse", "data")
    r = _publish_side(tmp_path, bare, artifact)
    assert r.returncode != 0
    assert wb._git(bare, "rev-parse", "data") == before
