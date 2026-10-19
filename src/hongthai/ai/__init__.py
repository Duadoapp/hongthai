"""AI 對決「三顆燈」（HD5，第四階段）：Claude 與 Gemini 各自讀一個機場的數據，給等級與四語短評。

- `config.py`：模型字串、免責四語、每報與每日上限（之後換模型只改那裡）
- `select.py`：要請 AI 評哪些機場
- `prompt.py`：系統提示與給模型看的精簡文字
- `parse.py`：模型回應的 JSON 檢查
- `claude.py`、`gemini.py`：各一個 `evaluate(text)`
- `run.py`：整個流程（平行呼叫、每日上限、`latest.json` 的 `ai` 欄位、對決戰績）
"""
