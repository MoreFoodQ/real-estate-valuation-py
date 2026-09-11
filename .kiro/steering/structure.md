# 專案結構與分層界線

前後端是兩個獨立的 repo。這份講後端，前端結構見下方。

```
real-estate-valuation-py/            後端（本 repo）
├── .kiro/                           steering、hooks
├── docs/
│   ├── ROBUSTNESS_AUDIT.md          穩健性稽核與調整點索引，先看這份
│   ├── official/                    官方書表、評價基準、作業手冊（不進版控）
│   ├── workshops/                   工作坊教材
│   └── reference/aws/               AWS Well-Architected
├── kernel/  parser/  pdfform/  api/ 四層，見下方分層界線
└── stress/                          壓力測試

real-estate-valuation/               前端（另一個 repo）
```

---

## 前端

```
src/
├── main.ts              入口：createApp → use(pinia) → use(router) → mount('#app')
├── App.vue              只有 <RouterView />，但全域 CSS 變數定義在這裡
├── router/index.ts      只有一個路由：'/' → HomeView
├── views/
│   └── HomeView.vue     唯一的頁面，所有畫面都在這
├── components/
│   ├── Table1Panel.vue      地價區段勘查表
│   ├── Table52Panel.vue     區域因素分析明細表
│   ├── Table4Panel.vue      比較法調查估價表，可點格子
│   └── EvidencePanel.vue    依據面板，顯示後端算好的依據鏈
├── stores/case.ts       Pinia store：一次上傳串三支 API
├── services/
│   ├── axiosService.ts      通用層：baseURL、攔截器、{data,error} 信封解析
│   └── valuationService.ts  端點與型別定義
├── types/case.ts        後端回傳資料的型別
└── composables/useLogger.ts
```

### 幾個關鍵事實

- **整個系統只有一個路由。** 沒有登入頁、列表頁、詳情頁，網址永遠是 `/`。
- **啟動時不打任何 API。** `src/` 裡沒有任何 `onMounted`，`store.analyze` 只在
  `HomeView.vue` 的 `onPick()` 與 `onDrop()` 被呼叫。後端關著畫面照樣正常出來。
- **首屏九成內容被 `v-if="parsed"` 關掉。** `parsed` 初始值是 `null`，那一大段
  template 不是隱藏，是根本沒有建立 DOM。
- **全域配色在 `App.vue` 的非 scoped `<style>`。** `--accent`、`--ok`、`--bad`
  等 CSS 變數都在那裡，改視覺風格從這 20 行下手，不用動每個元件。
- `EvidencePanel.vue` **刻意不做任何運算**，只顯示後端算好的依據鏈。

---

## 後端

```
real-estate-valuation-py-main/
├── paths.py             官方文件路徑常數，可用 VALUATION_DOC_DIR 覆寫
├── api/                 FastAPI 薄殼
│   ├── main.py          entry point，app 定義在這；7 支端點
│   ├── envelope.py      {data, error} 回應信封與錯誤處理
│   ├── kernel_api.py    唯一接進 kernel 的入口
│   ├── review.py        三層逐格比對
│   └── CONTRACT.md      端點與回應格式規格
├── kernel/              規則引擎（純 Python 零依賴）
│   ├── src/
│   │   ├── ruleset.py   規則集載入
│   │   ├── classify.py  值 → 等級
│   │   ├── matrix.py    等級對 → 修正率
│   │   ├── compute.py   加總、尾數處理、全鏈路試算
│   │   └── validate.py
│   ├── rules/*.json     規則集（目前只有金山商業用地）
│   └── golden/          官方範本的期望答案
├── parser/              PDF 辨識
│   ├── extract.py       pdfplumber 包裝：Word / Page 資料結構與座標查詢
│   ├── detect.py        判斷一頁是哪張表
│   ├── table1.py        走網格
│   ├── table5_2.py      走網格，28 項 factor_id 的正本對照表在這
│   ├── table4.py        走框線座標
│   ├── survey.py        表1 量測值 → 可分級的值
│   ├── provenance.py    欄位來源（頁碼、bbox、原文）
│   └── cli.py           不啟動服務就辨識
└── pdfform/             產出填好的官方書表
    ├── forms.py         build_forms()，被 api/main.py 呼叫
    ├── template.py      值該畫在哪（用 provenance 的 bbox 當版面定義）
    ├── fill.py          每格要填什麼
    └── render.py        reportlab 畫成 PDF
```

### API 端點

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/api/rulesets` | 列出可用規則集 |
| POST | `/api/parse` | 上傳 PDF → 辨識三張表 |
| POST | `/api/compute` | 重算表4 全鏈路 + 依據鏈 |
| POST | `/api/review` | 三層逐格比對 |
| POST | `/api/forms` | 產出三張書表，回傳下載連結 |
| GET | `/api/forms/{token}/{filename}` | 下載書表（回傳 PDF 本身，不走信封） |
| GET | `/api/health` | 健康檢查 |

---

## 分層界線（不要跨越）

```
parser/  ──→  api/  ──→  kernel/
   PDF 進來      只做 JSON      純計算
   座標抽取      進出與檔案      零依賴
                收發
```

- **`api/` 不做任何計算。** 一旦 API 開始自己算，「每個數字都指得回官方文件」
  的追溯鏈就斷在這一層。計算全部委派給 `kernel/`。
- **`kernel/` 零外部依賴，也不認識 PDF。** 輸入是 dict，輸出是 dataclass。
- **`pdfform/` 不 import `kernel/`。** 需要的計算函式（`appraise`、`classify`、
  `lookup`）由 `api/main.py` 以參數注入，相依方向由 api 決定。
- **`parser/survey.py` 刻意不 import kernel**，避免 pdfform 反向依賴 api。

## 資料流

```
使用者拖入 PDF
  └─ HomeView.onPick/onDrop
      └─ store.analyze(file)                    stores/case.ts
          ├─ parseForms(file)   POST /api/parse    → parsed
          ├─ compute(tables)    POST /api/compute  → computed
          └─ review(tables)     POST /api/review   → reviewed
              ↓ 三者共用同一份 tables，所以在 store 串起來，畫面只等一個 loading
          畫面 v-if="parsed" 成立，三張表與審查結果才渲染
```

產表是**分開觸發**的（`store.makeForms()`），因為要花幾秒，而多數時候使用者
只想看審查結果。書表必須從同一份原始檔產生，所以 store 留了 `sourceFile`。
