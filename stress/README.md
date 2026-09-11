# stress — 穩健性壓力測試

回答一個問題：**如果地政局給我們一份不同標的、不同結構、不同數值的查估書表，
系統會在哪裡炸開？**

這不是單元測試（那些在各模組的 `tests/`）。這裡刻意餵入畸形、極端、
與結構變異的輸入，記錄**失敗型態**，特別是「沒爆掉卻給錯答案」的情況——
那比拋出例外危險得多。

## 跑法

```bash
cd real-estate-valuation-py-main

# 產生合成規則集（第一次或改過生成規則時才需要）
.venv/bin/python -m stress.make_rulesets

# 跑全部壓力測試
.venv/bin/python -m stress.audit
```

需要官方範本 `docs/official/real-estate-valuation/查估書表範本.pdf`。
那份 PDF 不在版控裡，補檔方式見 `docs/README.md`。

## 測試分組

| 組 | 內容 | 為什麼要測 |
| --- | --- | --- |
| A 缺表 | 表1／表5-2／表4 的 7 種組合 | 官方可能分檔送，或只送要複查的那張 |
| B 標的數 | 0～4 件比較標的，權重給／不給 | 查估辦法第19條允許 1～3 件，範本只有 1 件 |
| C 數值 | 0、負數、極大、字串、None、空字串 | parser 誤讀時會送進什麼 |
| D 規則集 | 缺欄位、改 factor_id、挖級距、換 kind | 換行政區＝換一份 JSON，得確認換得動 |
| E 產表 | parse → fill → render → 再 parse | 自己產出的 PDF 讀不讀得回來 |
| F 偵測 | 同一張表出現多頁、空頁面清單 | 真實案件表格可能跨頁 |
| G 自檢 | `validate.check_ruleset()` 抓不抓得到 D 組製造的問題 | 確認既有防線的有效範圍 |

## 合成規則集

`fixtures/` 下的規則集是**壓力測試用的合成資料，不是官方資料**，
每一份的 `status` 都標為 `synthetic`。

刻意**不放進 `kernel/rules/`**，避免出現在 `/api/rulesets` 的清單裡
被誤認為系統真的支援那些行政區。要用的話以路徑載入：

```python
load_ruleset("stress/fixtures/testdistrict2-industrial-regional.json")
```

由金山商業用地規則集等比變換產生（級距 ×k、修正幅度 ×m 並同步 `max_range`），
用途是驗證「規則是資料，不是程式碼」這個主張真的成立。

## 結果解讀

`docs/ROBUSTNESS_AUDIT.md` 是這些測試跑出來的分析報告，含風險清單、
修正難度與優先序。跑完有差異時記得更新那份文件。
