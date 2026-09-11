# API 介面契約

前端已有統一的 axios 封裝（`real-estate-valuation/src/services/axiosService.ts`），
本契約以它為準，後端配合，不要求前端改攔截器。

## 一、回應信封（強制）

**每一個回應的 body 都必須是 `BaseResponse<T>`**：

```json
{ "data": <T> | null, "error": { "code": <int>, "message": "<string>" } | null }
```

三條硬規則，違反任一條前端攔截器就會判讀錯誤：

1. **`data` 與 `error` 二擇一，永不同時有值。** 成功時 `error: null`，失敗時 `data: null`。
2. **非 2xx 也必須維持這個形狀。** 攔截器用 `'error' in body && 'data' in body` 判斷是不是標準格式；
   FastAPI 預設的 `{"detail": "..."}` 不符合，會讓錯誤訊息掉回 axios 的通用 message。
   所以 `HTTPException` 與驗證錯誤都要接手改寫成信封格式。
3. **`error.code` 放 HTTP 狀態碼**（前端 `ErrorResponse.code` 註解為「通常為 HTTP 狀態碼」）。

成功／失敗由 **HTTP 狀態碼**決定（`success = status >= 200 && status < 300`），
不是看 body 裡有沒有 `error`。所以業務失敗要回真正的 4xx／5xx，不能回 200 夾一個 error。

前端會特別處理的狀態碼（`axiosService.ts` 的 switch）：`400` / `403` / `404` / `422` / `500`。
本 API 用到的：

| 狀態碼 | 時機 |
|---|---|
| 400 | 請求格式對但內容不合理（例如 PDF 裡找不到指定的表別） |
| 404 | 指定的規則集不存在 |
| 422 | 上傳的檔案不是 PDF、或缺必要欄位（FastAPI 驗證錯誤要改寫成信封） |
| 500 | 辨識或計算過程未預期的例外 |

## 二、命名慣例

- **信封層用 camelCase**：`data` / `error` / `code` / `message`，與前端型別一致（都是單字，無衝突）。
- **`data` 內的領域資料保持 snake_case**，與 `kernel/golden/case_1140901_99_001.json` 完全一致。

  理由：factor_id 本身就是帶點的 snake（`individual.road.frontage_road_width`），
  它是**資料的鍵**不是欄位名；為了 camelCase 而轉換，等於在辨識層與引擎層之間插一層
  雙向對照表，只會製造對不上的機會。前端的 TS 型別直接照 golden JSON 寫即可。

- 時間戳記若有需要，用 ISO 8601（前端 `CreatedResponse.createdAt` 的慣例）。

## 三、端點

基底路徑 `/api`，前端以 `VITE_API_URL` 指定 base URL。

### `GET /api/rulesets`

列出可用的規則集。Demo 現場抽換不同行政區的基準表要用。

```json
{ "data": { "rulesets": [
    { "ruleset_id": "jinshan_commercial_individual", "kind": "individual",
      "district": "新北市金山區", "land_use": "商業用地",
      "status": "complete", "factor_count": 19 },
    { "ruleset_id": "jinshan_commercial_regional", "kind": "regional",
      "district": "新北市金山區", "land_use": "商業用地",
      "status": "complete", "factor_count": 28 }
  ] }, "error": null }
```

`status` 必須誠實回報：`partial` 代表規則集還沒補完，前端要能顯示「只有 N/28 項
能算修正率」，而不是讓使用者以為全部都查過了。目前兩套都是 `complete`。

### `POST /api/parse`

`multipart/form-data`，欄位 `file`（PDF）。逐頁判斷表別並辨識。

```json
{ "data": {
    "case_id": "1140901-99-001",
    "pages": [ { "page": 1, "table": "表1" }, { "page": 4, "table": null } ],
    "tables": { "表1": { ... }, "表5-2": { ... }, "表4": { ... } },
    "provenance": { "benchmark.facts.individual.parcel.area":
                    { "page": 3, "bbox": [243.1, 124.4, 262.7, 131.5],
                      "raw_text": "113.21", "backend": "text_layer" } },
    "warnings": [ { "code": "grade_label_mismatch", "message": "...", "path": "..." } ]
  }, "error": null }
```

- `tables` 只包含這份 PDF 裡實際存在的表；缺表不是錯誤（官方可能分檔送）。
- `provenance` 的鍵是欄位路徑，值是來源。前端「點格子看依據」直接查這張表。
- `warnings` 是可繼續的問題（等級數字與文字不一致、單位可疑…），錯誤才用 `error`。

### `POST /api/compute`

body 是 `/api/parse` 回傳的 `tables` 加上規則集選擇。

```json
{ "tables": { ... },
  "ruleset_individual": "jinshan_commercial_individual",
  "ruleset_regional": "jinshan_commercial_regional" }
```

回傳全鏈路結果與依據鏈：

```json
{ "data": {
    "individual_total_pct": 13.0, "abs_sum_pct": 15.0,
    "regional_total_pct": 0.0,
    "trial_price": 212958, "benchmark_comparison_price": 212958,
    "benchmark_land_price_rounded": 213000,
    "corrections": [
      { "factor_id": "individual.road.frontage_road_width",
        "benchmark": { "value": 18, "grade": 2, "label": "稍優",
                       "reason": "18 落在「15m以上未滿20m」→ 第2級" },
        "comparable": { "value": 6, "grade": 4, "label": "稍劣",
                        "reason": "6 落在「4m以上未滿8m」→ 第4級" },
        "correction_pct": 5.0,
        "source": { "doc": "評價基準明細表範例.pdf", "page": 8 } }
    ]
  }, "error": null }
```

`corrections[].reason` 與 `source` 是 demo 的主論述（每個數字都能指回基準表哪一列），
資料結構沿用 `kernel/demo.py` 已經在印的依據鏈。

### `POST /api/review`

審查模式。body 同 `/api/compute`（`tables` 裡已含估價師填的 `filed_corrections`）。
逐格比對「人填的值」與引擎重算的值。

```json
{ "data": {
    "verdict": "mismatch",
    "layers": {
      "table1_internal": [],
      "table1_to_table5_2": [ { "factor_id": "regional.transport.main_road_width",
          "filed": { "grade": 2, "label": "稍優" },
          "computed": { "grade": 3, "label": "普通" },
          "basis": "表1 主要道路 18M；基準表「普通：15m以上未滿20m」",
          "impact_pct": -3.75 } ],
      "table5_2_to_table4": []
    },
    "price_impact": { "filed": 212958, "computed": 204972,
                      "diff_per_sqm": -7986 }
  }, "error": null }
```

三層對應手冊審查重點第 vi、vii 項（`土地徵收補償市價查估作業手冊` 印刷頁 11–13）。
`verdict` 取 `"match"` / `"mismatch"`。

### `POST /api/forms`

`multipart/form-data`，欄位 `file`（PDF）。產出三張**填好的**官方格式書表。

```json
{ "data": {
    "id": "ddcbe526206b4c519f0b3fab91a31c3b",
    "files": [
      { "table": "表1", "filename": "table1-survey.pdf", "size": 126841,
        "link": "/api/forms/ddcbe.../table1-survey.pdf" }
    ]
  }, "error": null }
```

回傳**檔案清單與連結**而不是檔案本身：信封規定 body 必須是 `{data, error}`，
二進位塞不進去。這個形狀比照前端既有的 `UploadedResponse`（id / link / updatedAt）。

### `GET /api/forms/{token}/{filename}`

下載產出的書表。**這是唯一不套信封的端點**——回傳 `application/pdf` 本身。
檔案下載本來就不適用 JSON 信封，前端也是用 `link` 直接開，不經過攔截器。

產出的檔案暫存在系統暫存目錄，服務重啟即消失。書表是衍生物不是資料，
重跑一次就有；留著反而要處理保存期限與個資。

## 四、CORS

只開本機來源，但**埠號用 regex 不寫死**：

```
allow_origin_regex = r"http://(localhost|127\.0\.0\.1):\d+"
allow_methods = ["GET", "POST"]
allow_headers = ["*"]
```

寫死 5173 踩過一次：vite 遇到埠被占用會自動往上找（實測掉到 5174），
這時整個前端突然連不上，而錯誤訊息完全看不出是 CORS。上線要換成明確的來源清單。

前端攔截器對「請求已發出但沒收到回應」只會記成網路錯誤，
CORS 沒開會表現成看不出原因的失敗，所以這條要先設好。

## 五、後端不做的事

- **不做認證。** `axiosService.ts` 的請求攔截器目前沒有加 Bearer token，
  `/auth/login`、`/auth/refresh` 的特例也只是預留。本 API 不需要登入。
- **不用預簽名上傳。** 前端有 `uploadFileToPresignedUrl`（MinIO/S3 用），
  但本 API 的 PDF 直接走 multipart 進 FastAPI，不經物件儲存。
