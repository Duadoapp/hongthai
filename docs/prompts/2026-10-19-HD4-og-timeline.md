# HD4：分享預覽圖——IATA 大字改 opsz 144、加未來 5 天 20 格的時間軸

模型：Opus，強度中。只改 `src/hongthai/og.py`、字型子集與測試；`latest.json`、各來源、`build.py` 的流程都不碰。

先讀 `docs/prompts/2026-10-19-HD1-og-image.md`（版面與預設值）、`src/hongthai/og.py`、`assets/fonts/README.md`、
`tools/make_font_subset.py`、`tests/test_og.py`。

## 1. IATA 大字改用 Fraunces opsz 144

- 用 fontTools `varLib.instancer` 再產一個靜態檔：`{"SOFT": 100, "wght": 600, "opsz": 144}`（`WONK` 留預設），
  子集同現在的 ASCII 範圍，存成 `assets/fonts/Fraunces-Soft600-Display.subset.ttf`；**只給 IATA 大字用**，
  英文機場名、日期時間、`duado.app/hongthai` 等小字維持現在的 opsz 9 那個子集
- `tools/make_font_subset.py` 同時產兩個 Fraunces 子集；`assets/fonts/README.md` 的表加一列；授權檔共用
  `OFL-Fraunces.txt`
- 涵蓋測試對兩個 Fraunces 子集都檢查

## 2. 未來 5 天 20 格的時間軸（網頁時間軸的縮小版）

位置：機場名（中英）下方、更新時間上方的空白處，寬度和左側文字區對齊（右側燈號區不要蓋到；三顆燈時版面
若擠，時間軸可以放到燈號下方整排橫跨，寬度 1200 − 2×64）。

- 20 格照 `slots` 的順序，每格一個**小圓角色塊**（例如寬約 44、高 28、圓角 8，格與格之間留 6 的縫；寬度依可用
  空間自動算，最多不超過 48）；顏色用網頁時間軸同一套晨光色：低 sage `#C2DCC6`、中 butter `#F3E3A5`、
  高 apricot `#F7C9A9`、已確認 text `#263038`、無資料（`unknown`／沒有等級）mapIdle `#D8DEE3`。
  顏色從 `og.LEVEL_COLORS` 取，不要另外寫一份；調色盤（固定色）要包含這些色塊和底色之間的反鋸齒中間色
- **每天第一格**下方標日期 `M/D`（該機場**當地時間**；一格的日期以它的 `from` 換成當地時間為準），用小字
  （Fraunces opsz 9 那個子集，約 20）；不標時刻。第一格如果不是當地那天的第一格也要標它的日期，
  之後遇到當地日期變了就標；一排最多 6 個日期
- 不畫框線、不畫陰影；色塊裡不寫字
- 燈號的小字（「最高：高　10/23 08–14 時」）維持

## 3. 測試與文件

- `tests/test_og.py` 加：時間軸 20 格的顏色對應（五種等級各至少一格）、日期標籤的位置與數量（UTC+8、UTC+9、
  UTC+10 各一個機場；跨當地午夜的格歸到正確的日期）、三顆燈時時間軸不與燈號重疊（用 bounding box 檢查）、
  兩個 Fraunces 子集的涵蓋；既有的 51 張都畫得出來、≤ 60 KB 照舊
- README「分享預覽圖」那節補時間軸與兩個 Fraunces 子集；`docs/prompts/2026-10-19-HD1-og-image.md` 不改
  （歷史文件）

## 回報時要附

- 桃園、關島、一個 UTC+9 的機場（例如羽田）三張圖的描述：IATA 字形、時間軸 20 格的顏色序列、日期標籤落在哪幾格
- 兩個 Fraunces 子集的大小；51 張的總大小與秒數

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修到綠（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
