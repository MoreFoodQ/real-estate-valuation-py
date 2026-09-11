# 文件目錄

文件與正式程式專案分開保存。正式執行時使用的程式與規則位於：

- `../real-estate-valuation-main/`：Vue 前端
- `../real-estate-valuation-py-main/`：FastAPI、PDF parser、規則引擎與產表程式

## 先看這一份

- **`PROJECT_DECISIONS.md`**：**唯一權威來源。** 已鎖定的決策、官方硬約束、
  已驗證的實測數字、風險與處置、待決事項，以及決策變更紀錄。
  與其他文件衝突時以這份為準。`.kiro/steering/decisions.md` 會自動載入它。

## 接著看這三份

- **`COMPETITION_BRIEF.md`**：競賽總覽。把主辦單位分散在多封信、PDF 與 Excel 裡的
  時程、規範、命題內容、評分配比、AWS 服務白名單、資源限制，整理成一份可直接查的
  注意事項，並附上對本專案的具體影響評估。人可讀，也可直接餵給 AI 當背景知識。
- **`PITCH_PLAN.md`**：6 分鐘簡報規劃。含實測數字、亮點盤點、流程圖、逐段 demo 腳本、
  可擴充性、創意方向、現場時程與問答準備。所有數字都是實際執行後端取得的。
- **`ROBUSTNESS_AUDIT.md`**：穩健性稽核。61 個壓力測試案例的結果、寫死與彈性規則的
  完整盤點、風險清單與修正優先序，以及現場拿到新書表時的止損策略。

## 分類

- `official/real-estate-valuation/`：估價系統使用的官方書表、評價基準與作業手冊
- `competition/`：黑客松題目、競賽說明、環境規範與參賽者資料
- `workshops/`：工作坊教材
- `reference/aws/`：AWS Well-Architected 參考資料

### `competition/` 內容

| 檔案 | 內容 |
| --- | --- |
| `【命題文件】地政局-新北市政府AI黑客松競賽.pdf` | 官方命題 |
| `隊員必讀題目白話說明.docx` | 題目白話版 |
| `2026新北市AI智慧城市黑客松競賽實戰工作坊.pdf` | 賽前工作坊教材 |
| `黑客松競賽環境規範與限制_20260722.pdf` | AWS 環境使用規範、Bedrock 與運算資源限制 |
| `Supported AWS Services List 20260722.xlsx` | 可用服務白名單（315 項）、EC2 與 SageMaker 配額 |

後兩份規範文件的重點已整理進 `COMPETITION_BRIEF.md`，平常查那一份就夠，
原始檔留著是為了核對與引用。

⚠️ **憑證不入庫**：競賽 Access Code 等憑證一律不寫入任何檔案。
需要時請直接貼進終端機。根目錄 `.gitignore` 已排除 `*.local.md` 與 `*.local` 作為後備防線。

後端預設從 `official/real-estate-valuation/` 讀取官方文件；若部署環境使用其他位置，
請設定 `VALUATION_DOC_DIR`。規則引擎實際計算使用的是後端內建的
`real-estate-valuation-py-main/kernel/rules/*.json`，官方 PDF 是來源與驗證文件。
