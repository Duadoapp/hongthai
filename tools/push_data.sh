#!/usr/bin/env bash
# 把 data 分支 worktree（目前目錄）的變更 commit 並推上去（HD20）。
# build.yml（每天四次）和 events.yml（每小時）可能同時推，所以推之前先 rebase 到遠端最新的 data，
# 失敗（被別人先推、網路）重試 3 次、間隔 20 秒。兩邊寫的檔案不重疊，rebase 不會衝突；
# 萬一衝突就放棄這次 rebase、下一輪重來。
set -u
git add -A
if git diff --cached --quiet; then
  echo "沒有新檔案"
  exit 0
fi
git -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit -q -m "${1:-data}: $(date -u +%Y-%m-%dT%H:%MZ)"
for attempt in 1 2 3 4; do
  if git ls-remote --exit-code --heads origin data > /dev/null; then
    if ! git -c user.name="github-actions[bot]" \
        -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
        pull -q --rebase origin data; then
      git rebase --abort 2> /dev/null || true
      echo "::warning::第 $attempt 次 rebase 失敗"
    elif git push -q origin HEAD:data; then
      exit 0
    fi
  elif git push -q origin HEAD:data; then
    exit 0
  fi
  if [ "$attempt" -lt 4 ]; then
    echo "第 $attempt 次推失敗，20 秒後重試"
    sleep 20
  fi
done
echo "::error::data 分支推了 4 次都失敗"
exit 1
