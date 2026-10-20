# HD18：估算陣風的係數改成「每個機場、30 天、IFS＋GFS 自己的陣風÷平均風中位數」（取代固定 1.4）

模型：Opus，強度中。改 `src/hongthai/sources/ecmwf.py`、`sources/gfs.py`（多留 10 米平均風速）、`assess.py`（估算陣風用機場係數）、
`config.py`、`build.py`（樣本檔、係數檔、輸出欄位）、新工具 `tools/gust_factor_report.py`、測試、README、`docs/ORCHESTRATOR.md`。
**`latest.json` 既有欄位不改名、不改型別**；只加 `models[]` 的 `windKt`、`gustFactor`、`gustFactorBasis` 三個鍵。

先讀 `docs/ORCHESTRATOR.md`「多模式投票」那條（含 HD18 定案）、`src/hongthai/assess.py`（`estimated_for_slot`、`model_entries`、
`ec_for_slot`、`gfs_for_slot`）、`sources/ecmwf.py`（`GustInterval`、`parse_hres`，`10u`／`10v` 只在 6 小時整步長）、`sources/gfs.py`
（`GustPoint`、`parse_file`）、`grib.py`（`wind_dir_from_uv`）、`build.py`（`data` 分支 `history/` 的讀寫、`REUSE_FIELDS`、
`_rescore`、`history/ai/` 的寫法）、`tests/test_vote.py`、`tests/test_assess.py` HD14 的案例。

## 定案（Shawn 2026-10-20 10:29 確認，12 條＋1 補充）

背景：拿 AIFS／AIGFS 同一格去比 `ec.hresGustKt` 不公平——颱風路線不同時同一格本來就差很多；而且只看 30 個平靜機場，GFS 自己的
真陣風也只有 IFS 的 0.76，IFS 陣風本身偏高、不能當標準答案。所以改成「同一模式自己的陣風÷平均風」：

1. 係數 G ＝ 陣風 ÷ 10 米平均風，用 IFS（HRES `10fg` ÷ √(u10²+v10²)）與 GFS（`GUST` ÷ 10 米風速）**各自**的資料算；同一模式、
   同一機場、同一格自己比自己
2. **每個機場一個係數**：最近 30 天、每報每格，IFS 與 GFS 的比例合在一起取中位數
3. 只用平均風 ≥ 10 節的格（`GUST_FACTOR_MIN_WIND_KT = 10`）
4. G 夾在 **1.2～2.0**（`GUST_FACTOR_RANGE`；夾在中位數上，不是夾樣本）
5. 樣本不足的順序：機場合格樣本 < 40（`GUST_FACTOR_MIN_SAMPLES`）→ 全部機場合併的 30 天中位數；合併也 < 40 → 這一報
   IFS＋GFS 的全體中位數（所有機場、所有格）；這一報一個 ≥ 10 節的格都沒有 → 固定 1.4（`GUST_FACTOR_DEFAULT`，保底）
6. 套用：AIFS、AIGFS 的 `gustKt` ＝ 自己的平均風 × 該機場 G，`gustEstimated: true` 照舊；`models[]` 每筆加 `gustFactor`（數字，
   兩位小數）和 `gustFactorBasis`（`airport30d`／`all30d`／`run`／`default`），IFS、GFS、系集那幾筆這兩個是 null
7. 存平均風：`models[]` 每筆加 `windKt`（10 米平均風，節，一位小數；IFS、GFS 是真的、AIFS、AIGFS 是自己的、系集 null）。
   IFS 一格取**格結束步長**的 `10u`／`10v` 風速（和風向同一個時間點）；GFS 取格內時間點裡**陣風最大那一點**的風速
8. 30 天後驗證：工具 `tools/gust_factor_report.py`（見第 4 節）
9. 樣本存 `data` 分支 `history/gustfactor/<YYYY-MM>.jsonl`，一行一報一機場，**IFS、GFS 分開記**：
   `{"run": "...", "icao": "RCTP", "ifs": [1.45, 1.52, ...], "gfs": [1.31, ...]}`（只存合格的比例，兩位小數，照格的順序；空的寫 `[]`）；
   算出的係數另存 `history/gustfactor/latest.json`：`{"generatedAt": ..., "window": {"from": ..., "to": ...},
   "all": {"g": 1.47, "n": 1234, "nIfs": ..., "nGfs": ...}, "airports": {"RCTP": {"g": 1.52, "n": 88, "nIfs": 44, "nGfs": 44,
   "basis": "airport30d"}, ...}}`
10. 樣本：一格一個比例——IFS 用該格的 `hresGustKt` ÷ 格結束步長的平均風；GFS 用該格 `gustKt` ÷ 同一時間點的平均風；平均風
    < 10 節的格不收。**Shawn 的補充**：IFS 的 `10fg` 是時段內最大陣風、GFS 的 `GUST` 是該時間點的陣風，定義不同；合在一起取
    中位數可以接受，但樣本檔與報表要**分開記、分開印**，30 天後看兩者差多少，再決定要不要只用其中一個
11. 沿用時：`ecmwf`／`gfs` 失敗、用 24 小時內舊資料的那一報，不寫新樣本（那個模式那一報的 `ifs`／`gfs` 寫 `[]`），G 照 30 天
    窗算
12. 編號 HD18，排在 HD14 之後

## 1. 來源多留平均風（`sources/ecmwf.py`、`sources/gfs.py`）

- `GustInterval` 加 `wind_kt: float | None`（區間結束那個 6 小時步長的 10 米風速，節；`10u`／`10v` 本來就有讀，算風向時一起算
  風速）；`GustPoint` 加 `wind_kt`（同一時間點，`UGRD`／`VGRD`）
- 下載量、請求數不變（不多抓參數）

## 2. 係數（`assess.py`、`config.py`、`build.py`）

- `config.py`：`GUST_FACTOR_DEFAULT = 1.4`、`GUST_FACTOR_RANGE = (1.2, 2.0)`、`GUST_FACTOR_MIN_WIND_KT = 10`、
  `GUST_FACTOR_MIN_SAMPLES = 40`、`GUST_FACTOR_WINDOW_DAYS = 30`；舊的 `GUST_FACTOR` 拿掉（或改名成 `GUST_FACTOR_DEFAULT`）
- `build.py` 每報：
  1. 先算這一報的樣本：每機場每格，IFS `hresGustKt`／`windKt`（`windKt ≥ 10`）、GFS `gustKt`／`windKt`；沿用的模式那一報不算
  2. 追加到 `history/gustfactor/<YYYY-MM>.jsonl`（`--archive` 下；同 `history/ai/` 的寫法）
  3. 讀最近 30 天（含這一報）的樣本算每機場 G：`basis` 照第 5 條；寫 `history/gustfactor/latest.json`
  4. 把 G 交給 `assess`：`estimated_for_slot(..., gust_factor=G)`，`models[]` 的 AIFS、AIGFS 那筆填 `gustFactor`／`gustFactorBasis`，
     投票照舊
- `_rescore`（沿用 AIFS／AIGFS 舊數字時）：抄來的 `gustKt` 已經是估算值，**用抄來的 `windKt × 這一報的 G` 重算**，不要沿用舊 G
- 首報（`history/gustfactor/` 還沒有）：`basis: "run"`；30 天窗用 `run` 時間比，跨月要讀兩個月份的檔

## 3. 輸出

- `slots[].model.models[]` 每筆多 `windKt`（數字或 null）、`gustFactor`（數字或 null）、`gustFactorBasis`（字串或 null）
- `latest.json` 大小回報（預估多 100–150 KB）

## 4. 工具 `tools/gust_factor_report.py`（30 天後驗證用，現在就寫好）

- 讀 `data` 分支（路徑用參數給）`history/<時間>.json` 的**第一格**（`now` 所在的格）與同一份的 `airports[].metar`：每個模式的
  `gustKt`（AIFS、AIGFS 是估算）對 METAR 的「有陣風用陣風、沒有用平均風」，印每模式的偏差中位數、平均比值、樣本數（只算
  METAR 在 3 小時內、且 METAR 風 ≥ 10 節的）；**IFS、GFS、AIFS、AIGFS 分開印**
- 另印 `history/gustfactor/` 的統計：每機場 IFS 中位數、GFS 中位數、合併中位數、樣本數，**IFS 與 GFS 分開一欄**，最後一行全部
  機場合併
- 純標準輸出、不改任何檔案；README「怎麼跑」補用法

## 5. 測試與文件

- `tests/test_sources_*`：`GustInterval.wind_kt`／`GustPoint.wind_kt` 從 u／v 算對
- `tests/test_gust_factor.py`（新）：樣本只收 ≥ 10 節；中位數；夾 1.2～2.0；機場 < 40 → `all30d`；全部 < 40 → `run`；沒樣本 →
  `default` 1.4；30 天窗（31 天前的不算、跨月）；沿用那報寫 `[]`
- `tests/test_assess.py`：AIFS 平均風 20 節、G 1.6 → `gustKt` 32、`gustFactor` 1.6；`model.ec`／`gfs` 既有測試不變；
  `tests/test_build.py`：`history/gustfactor/` 兩個檔的格式、`models[]` 三個新鍵
- README「怎麼算」估算陣風那段改寫（定義、30 天、每機場、夾 1.2–2.0、樣本不足順序、IFS／GFS 定義不同先合併看）、「輸出」加
  三個鍵、「`data` 分支」加 `history/gustfactor/`；`docs/ORCHESTRATOR.md` HD18 那條補「已實作」與不一樣的地方

## 回報時要附

- 合併前用 `data` 分支最近幾報算一次：全部機場合併的 IFS 中位數、GFS 中位數、合併中位數與樣本數（這就是首報會用的 `run` 值）
- 桃園、關島、羽田三個機場的樣本數與 G（會是 `run`，因為還沒 30 天）
- `latest.json` 大小

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
