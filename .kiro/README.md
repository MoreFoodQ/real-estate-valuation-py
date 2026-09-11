# .kiro

Kiro 在這個專案的使用紀錄。依 2026 新北市 AI 智慧城市黑客松競賽規範，
本資料夾必須存在於專案根目錄，且不得加入 `.gitignore`。

```
.kiro/
├── steering/     專案背景知識，每次對話自動載入
├── hooks/        事件觸發的自動化
└── specs/        功能開發紀錄（需求 → 設計 → 任務）
```

## steering/

每次與 Kiro 對話時自動帶入的專案知識。內容全部來自實際閱讀程式碼與
執行驗證，不是推測。

| 檔案 | 內容 |
| --- | --- |
| `product.md` | 這個系統在解什麼問題：土地徵收補償查估書表的三層審查。含核心設計主張與已知限制 |
| `tech.md` | 技術棧、啟動指令、各測試套件實測耗時，以及環境陷阱（node 不在 PATH、e2e 不在 type-check 範圍內） |
| `structure.md` | 目錄結構、API 端點、分層界線、完整資料流 |
| `competition.md` | 競賽硬規定，並以 `#[[file:]]` 引用 `docs/COMPETITION_BRIEF.md` 完整版 |

`tech.md` 與 `structure.md` 記錄的環境陷阱是實際踩過才發現的，例如：

- `node` 與 `npm` 不在系統 PATH，可攜式 Node 在 `real-estate-valuation-main/.tools/`
- `npm run type-check` 檢查不到 `e2e/`，因為 `tsconfig.json` 的 references 沒包含它
- `kernel` 測試 0.5 秒，但 `parser` / `pdfform` / `api` 要 20–30 秒（都得真的解 PDF）

## hooks/

| 檔案 | 觸發 | 作用 |
| --- | --- | --- |
| `kernel-tests-on-save.json` | `PostFileSave`，比對 `kernel/**/*.{py,json}` | 跑 90 個規則引擎測試。選 kernel 是因為它只花 0.5 秒（純邏輯零依賴），而規則引擎是整個系統可信度的根基 |
| `guard-secrets-before-commit.json` | `PreToolUse`，比對 `execute_bash` | 檢查 staged 檔案是否疑似含憑證，命中則要求確認。競賽規範禁止上傳 Access Key 等憑證，而 `docs/competition/ACCESS.local.md` 存有競賽 Access Code |

第二個 hook 的比對規則刻意排除 `.kiro/`。實測發現不排除的話，
`guard-secrets-before-commit.json` 這個檔名本身就會命中 `secret` 而誤判，
把競賽強制要求上傳的資料夾攔下來。三項驗證：`.kiro/` 不誤判、
`ACCESS.local.md` 會被抓到、`.env.development`（只含 API 位址）正確略過。

## specs/

目前是空的。

原因：spec 是「需求 → 設計 → 任務」的開發紀錄，這個專案的既有程式是在
導入 Kiro 之前完成的，替已經寫好的程式倒推一份 spec 沒有意義。
接下來的功能開發會實際走 spec 流程，屆時紀錄會出現在這裡。

已排入候選的題目：

- **接上 `/api/rulesets`**：後端端點已可用，`valuationService.ts` 也已定義
  `listRulesets()`，但前端沒有任何地方呼叫它。接起來可在畫面上抽換不同行政區
  的評價基準
- **書表改存 S3**：目前存在 `tempfile.gettempdir()`，部署到 Lambda 會導致
  產表後下載不到檔案。這是部署前的必要改動
