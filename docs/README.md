# 文件目錄

專案文件與官方參考資料。程式在上一層各模組目錄，前端在
[`real-estate-valuation`](https://github.com/MoreFoodQ/real-estate-valuation)。

## 先看這一份

- **`ROBUSTNESS_AUDIT.md`**：穩健性稽核。壓力測試結果、寫死與彈性規則的完整盤點、
  風險清單與修正優先序、格式變異的實測行為，以及症狀對照的調整點索引。
  改 `parser/` 之前先看第 4 與第 10 節。

技術立場與已知限制寫在 `../.kiro/steering/decisions.md`。

## 分類

- `official/real-estate-valuation/`：估價系統使用的官方書表、評價基準與作業手冊
- `workshops/`：工作坊教材
- `reference/aws/`：AWS Well-Architected 參考資料

⚠️ **憑證不入庫**：Access Key、API Token 等一律不寫入任何檔案，
需要時直接貼進終端機。根目錄 `.gitignore` 已排除 `*.local.md` 與 `*.local`
作為後備防線。

⚠️ **官方 PDF 不在版控裡**（約 103MB，見根目錄 `.gitignore`）。全新 clone 之後
`parser` 與 `pdfform` 的測試會因為找不到「查估書表範本.pdf」而失敗，需自行補檔。
`kernel` 與 `api` 的測試不受影響。

後端預設從 `official/real-estate-valuation/` 讀取官方文件；若部署環境使用其他
位置，請設定 `VALUATION_DOC_DIR`。規則引擎實際計算使用的是 `kernel/rules/*.json`，
官方 PDF 是來源與驗證文件。
