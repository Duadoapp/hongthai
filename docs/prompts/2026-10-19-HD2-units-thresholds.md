# HD2：風速一律用節、新的陣風／側風門檻、系集機率改節的門檻

模型：Opus，強度高。這支改等級規則與單位，`latest.json` 既有欄位不改名、不改型別（`hresGustMs`、`gustMs`、
`p10`／`p15`／`p25` 都保留照出），只加欄位。要在 H9（41 個機場）之前合併。

先讀 `docs/ORCHESTRATOR.md`、`README.md`、`src/hongthai/assess.py`、`src/hongthai/config.py`（`Thresholds`）、
`src/hongthai/sources/ecmwf.py`（`ENS_PARAMS`、`parse_ens`）、`airports.json`、`tests/test_assess.py`、`tests/test_build.py`。

## 決定（Shawn 2026-10-19 定案）

1. **一律用節**：等級規則內部、log、之後的 AI 短評與預覽圖都用節，不再用 m/s。模式陣風在解析完就換算成節
   （1 m/s = 1.943844 節），`Thresholds` 裡所有風速門檻改成節
2. **陣風門檻（官方 TAF 與模式同一套）**：中 ≥ 37 節（蒲福 8 級）、高 ≥ 48 節（10 級）。依據：桃園機場空橋規則，
   最大瞬間風速 37 節啟動空橋防護、48 節空橋停用、55 節以上全部綁死。TAF 平均風 ≥ 35 節算高維持不變
3. **側風門檻**：中 ≥ 27 節、高 ≥ 33 節（原本 25／35）。依據：窄體客機常見作業限制，737-800 濕跑道起飛約 27 節、
   乾跑道約 33 節
4. **ECMWF 系集機率改用節的門檻**：28、37、48 節（7、8、10 級）。28 節只當參考、不進等級規則；37、48 對應中、高。
   但 ECMWF 開放資料的機率產品只有 `10fgg10`／`10fgg15`／`10fgg25`（≥ 10／15／25 m/s，即 ≥ 19.4／29.2／48.6 節），
   沒有 37 節的——怎麼處理見下面第 3 節
5. 所有機場先用同一套門檻，之後找到個別機場的作業標準再在 `airports.json` 覆寫（覆寫機制已經有）
6. 之後新天氣種類的單位：雨量毫米、能見度公尺、積雪公分（這支不做，先記在 README）

## 要做的事

### 1. 單位與門檻

- `config.py` 的 `Thresholds` 改成（鍵名也改，舊鍵不再接受；`airports.json` 五個機場同步改）：

  ```
  modelMediumGustKt: 37
  modelHighGustKt: 48
  tafMediumGustKt: 37
  tafHighGustKt: 48
  tafHighWindKt: 35
  crosswindMediumKt: 27
  crosswindHighKt: 33
  ecP49High: 0.3        # 系集 ≥ 25 m/s（≈49 節）機率 ≥ 30% → 高
  ```

  原本的 `ecP15Medium` 拿掉（中級不用系集，見第 3 節）
- `assess.py`：規則改成節；側風本來就是節；docstring 開頭的規格說明整段改寫成節，並記下門檻的依據（上面 2、3）
- `ecmwf.py`／`gfs.py`：陣風解析後換算成節（`EcmwfPoint`、`GustPoint` 存節；為了契約，輸出時 `hresGustMs`／`gustMs`
  仍用 m/s 算回去，或同時保留兩個值），側風計算用節的陣風
- log 裡的風速一律印節

### 2. `latest.json` 加的欄位（規格以外、要進 spec 第 16 節；舊欄位全部保留）

- `slots[].model.ec.hresGustKt`、`slots[].model.gfs.gustKt`：節，一位小數（`hresGustMs`／`gustMs` 照舊）
- `slots[].model.ec.p29Kt`、`p37Kt`、`p49Kt`：系集「陣風 ≥ 29／37／49 節」的機率（0–1）。`p29Kt` 的值就是
  `p15`（15 m/s ≈ 29.2 節）、`p49Kt` 就是 `p25`（25 m/s ≈ 48.6 節）；`p37Kt` 目前沒有來源，一律 `null`
  （保留給之後接 GEFS 系集成員自己算）。README 寫清楚這三個欄位實際對應的 m/s 門檻
- `thresholds` 這份輸出裡若有列出門檻的地方（`airports[].thresholds`，若目前有輸出），改成新的鍵

### 3. 中級的系集規則（Shawn 2026-10-19 定案）

ECMWF 開放資料沒有 ≥ 37 節的機率，所以：
- 中級**不用系集**，只看 HRES／GFS 的確定性陣風 ≥ 37 節（和 TAF 陣風 ≥ 37 節）
- 高級：系集 `p49Kt` ≥ 30%，**或**確定性陣風（HRES／GFS／TAF）≥ 48 節
- `p29Kt` 只輸出、只顯示，不進規則；`p37Kt` 一律 `null`（之後另一支 HD 用 GEFS 系集成員自己算）
- `agreement` 規則不變（HRES 與 GFS 的陣風落在同一級）

### 4. 驗算：2026-10-18 16:15Z 那一報的真實案例

`data` 分支 `history/20261018T1615Z.json`（`git fetch origin data` 後 `git show data:history/20261018T1615Z.json`）
是第一個真實強風案例：10/23 桃園、松山、高雄都是 high，高雄 10-23T06 的模式側風 50.5 節。請用那份檔案裡
的數字（`hresGustMs`、`gustMs` 換算成節、`crosswindKt`、`p25`、TAF 時段），分別用**舊門檻**與**新門檻**重算五個機場
每一格的 `level`，把**有差異的格**列成表（機場、`from`、舊等級、新等級、為什麼）放進 PR 說明；
同時寫成測試 `tests/test_assess.py::test_real_case_20261018_1615z`（把需要的幾格數字抄進測試當 fixture，
不要把整份 JSON 放進 repo）。

### 5. 文件與測試

- README「怎麼算」的表整個改成節、門檻依據一句話；「輸出」範例與「規格以外加的欄位」補新欄位；
  「已知的保守假設與待校準的參數」改成新數字
- `docs/ORCHESTRATOR.md`「已知的保守假設與待校準的參數」同步
- `tests/test_assess.py` 的門檻案例全部改成節；`tests/test_build.py` 契約測試加新欄位
- 不要動 `airports.json` 的機場清單（H9 才加）、不要動 `cancellations.py`

## 回報時要附

- 新舊門檻下 16:15Z 那一報的差異表
- `Thresholds` 最後的鍵與預設值

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修到綠（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
