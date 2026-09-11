# real-estate-valuation-py

2026 新北市 AI 智慧城市黑客松「AI 輔助不動產估價案件審查」（地政局命題）的**後端**。

## 兩個 repo

前後端分離，各自獨立部署，溝通只透過 HTTP。

| repo | 內容 |
|---|---|
| **`real-estate-valuation-py`**（本專案） | 規則引擎、書表辨識、產表、API，以及 `docs/` 完整專案文件 |
| [`real-estate-valuation`](https://github.com/MoreFoodQ/real-estate-valuation) | Vue 3 + TypeScript 前端 |

## 先讀這些文件

| 文件 | 內容 |
|---|---|
| [`docs/PROJECT_DECISIONS.md`](docs/PROJECT_DECISIONS.md) | **唯一權威來源。** 已鎖定的決策、官方硬約束、已驗證的實測數字、風險與處置、決策變更紀錄 |
| [`docs/COMPETITION_BRIEF.md`](docs/COMPETITION_BRIEF.md) | 競賽總覽：時程、命題、評分配比、AWS 服務白名單、資源限制 |
| [`docs/PITCH_PLAN.md`](docs/PITCH_PLAN.md) | 簡報規劃：實測數字、流程圖、demo 腳本、問答準備 |
| [`docs/ROBUSTNESS_AUDIT.md`](docs/ROBUSTNESS_AUDIT.md) | 穩健性稽核：61 個壓力測試案例、寫死與彈性規則盤點、修正優先序 |

## 內部分工

| 目錄 | 內容 |
|---|---|
| `kernel/` | 規則引擎（純 Python、零第三方依賴） |
| `parser/` | 書表 PDF 辨識（pdfplumber 座標抽取） |
| `pdfform/` | 把重算結果填回官方版面，產出可交件 PDF |
| `api/` | FastAPI 薄殼，只做 JSON 進出 |
| `stress/` | 穩健性壓力測試 harness |
| `docs/official/real-estate-valuation/` | 估價官方文件（PDF，不進版控） |

分層規定：`kernel/` → `parser/` → `api/`，**kernel 不得反向依賴 parser / api**。
kernel 是純邏輯、零第三方依賴；PDF 解析屬 adapter，不能滲進 domain core。
api 只做 JSON 進出與檔案接收，**沒有任何計算邏輯**——demo 的主論述是
「每個數字都能指回官方文件」，API 層一旦自己算，追溯鏈就斷在那裡。

## 前置

- **Python 3.13+**（本機以 3.13.7 測試）
- **官方文件目錄**。預設從本專案的 `docs/official/real-estate-valuation/` 讀取
  （定義在 `paths.py`）。放在別處時設環境變數：

  ```bash
  export VALUATION_DOC_DIR="/path/to/docs/official/real-estate-valuation"
  ```

  ⚠️ **官方 PDF 不在版控裡**（約 103MB，`.gitignore` 排除）。全新 clone 之後
  `parser` 與 `pdfform` 的測試會因為找不到「查估書表範本.pdf」而失敗，需自行補檔。
  `kernel` 與 `api` 的測試不受影響。

## 安裝

macOS / Linux：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows（PowerShell）：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

`kernel/` 不需要任何套件就能跑；`requirements.txt` 裡的都是 `parser/` 與 `api/` 用的。

## 啟動

### 1. 啟動 API

```powershell
cd D:\SideProject\real-estate-valuation-py
python -m uvicorn api.main:app --reload --port 8000
```

確認活著：

```powershell
curl http://127.0.0.1:8000/api/health
# {"data":{"status":"ok","doc_dir":".../docs/official/real-estate-valuation"},"error":null}
```

互動式文件在 <http://127.0.0.1:8000/docs>。前端把 `VITE_API_URL` 指到
`http://localhost:8000` 即可——CORS 開的是 `http://localhost|127.0.0.1:任意埠`，
因為 vite 遇到 5173 被占用會自動往上找（實測會掉到 5174），
寫死白名單會讓前端突然連不上而且看不出原因。

端點：

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/health` | 存活檢查，順便回報文件目錄位置 |
| GET | `/api/rulesets` | 可用規則集（demo 現場抽換基準表用） |
| POST | `/api/parse` | 上傳查估書表 PDF → 三張表的辨識結果 + provenance |
| POST | `/api/compute` | 依規則集重算表4 全鏈路 + 依據鏈 |
| POST | `/api/review` | 審查模式：三層逐格比對 + 賠償金差額 |
| POST | `/api/forms` | **產出三張填好的官方書表 PDF**，回傳下載連結 |
| GET | `/api/forms/{token}/{filename}` | 下載產出的書表（回傳 PDF 本身，不走信封） |

**回應格式是固定的信封** `{"data": …, "error": …}`，二擇一，錯誤回應也一樣。
這是配合前端既有的 `axiosService.ts` 攔截器，完整契約見 [api/CONTRACT.md](api/CONTRACT.md)。

### 2. 不啟動服務，直接用命令列辨識

```powershell
python -m parser.cli "..\docs\official\real-estate-valuation\查估書表範本.pdf"
```

```
p1  表1
p2  表5-2
p3  表4
p4  （非書表：圖或其他）
p5  （非書表：圖或其他）
p6  （非書表：圖或其他）
```

```powershell
python -m parser.cli "..\docs\official\real-estate-valuation\查估書表範本.pdf" 表4 --provenance
```

### 3. 產出三張填好的官方書表

```powershell
python -m pdfform.cli "../docs/official/real-estate-valuation/查估書表範本.pdf" out
```

```
表1     out	able1-survey.pdf（124 KB）
表5-2   out	able5_2-regional.pdf（94 KB）
表4     out	able4-comparison.pdf（105 KB）
```

版面不是自己畫的：框線是向量物件、靜態欄位名是文字，兩者都從官方書表抽出來，
只有「值」那些格子換成引擎算出來的內容。詳見 `pdfform/template.py`。

### 4. 規則引擎重現官方答案

```powershell
cd kernel
python demo.py
```

```
個別因素合計 13.00%   絕對值加總 15.00%
試算價格 212,958      比準地比較價格 212,958      比準地地價 213,000
```

### 5. 測試

```powershell
cd D:\SideProject\real-estate-valuation-py
python -m pytest -q          # 全部：163 passed
python -m pytest kernel -q   # 引擎  90
python -m pytest parser -q   # 辨識  44
python -m pytest api -q      # 介面  20
python -m pytest pdfform -q  # 產表   9
```

> 兩個子專案各有自己的 `conftest.py`。根目錄的把專案根放上 `sys.path`（提供 `parser` / `api` 套件），
> `kernel/conftest.py` 把 `kernel/` 放上（提供 `src`）。兩者不重疊，所以能一起跑。

## 目錄

```
kernel/          規則引擎（純 Python 零依賴）
  rules/         規則資料 —— 唯一需要隨案件更換的東西
  src/           classify / matrix / compute / validate / ruleset
  golden/        官方已填範本作為測試答案
  demo.py        一鍵重現 + 依據鏈輸出
parser/          書表辨識層
  extract.py     PDF 文字層、框線與 cell 網格抽取
  detect.py      依標題判斷一頁是哪張表
  table1.py      表1 地價區段勘查表（28 個細項的等級與量測值）
  table5_2.py    表5-2 影響地價區域因素分析明細表（28 細項 + 8 小計 + 總修正數）
  table4.py      表4 比較法調查估價表（19 個個別因素 + 價格鏈）
  provenance.py  欄位級來源記錄
  golden/        表5-2 的期望值 fixture
  cli.py         命令列入口
pdfform/         產出填好的官方書表 PDF
  template.py    從官方書表抽出版面（框線、靜態欄位名、可填格子）
  fill.py        決定每一格填什麼（輸入照抄、該算的一律重算）
  render.py      畫成 PDF
  forms.py       辨識 → 計算 → 產表 一次做完
  cli.py         命令列入口
api/             FastAPI 薄殼
  main.py        端點
  envelope.py    回應信封與錯誤改寫
  review.py      三層審查比對
  kernel_api.py  接進 kernel 的唯一入口
  CONTRACT.md    介面契約（以前端 axiosService.ts 為準）
paths.py         外部文件位置（VALUATION_DOC_DIR）
```

## 目前進度

| 項目 | 狀態 |
|---|---|
| 規則引擎（個別因素 19 項、分級／查表／加總／價格／尾數） | ✅ |
| 表4 辨識器 | ✅ facts 與 golden JSON 逐項相符 |
| 表5-2 辨識器 | ✅ 28 細項 + 8 群組小計 + 總修正數 |
| 表1 辨識器 | ✅ 28 細項的等級／級數／量測值 |
| API（parse / compute / review / rulesets） | ✅ 端到端 212,958 / 213,000 |
| 規則引擎（區域因素 28 項） | ✅ validator 0 ERROR / 0 WARN |
| 審查模式三層比對 | ✅ 三層全部完整，官方範本逐格比對 77 格 |
| 產出三張填好的官方書表 PDF | ✅ 往返測試：產出的 PDF 再辨識一次，值與官方答案相同 |
| vision 備用路徑（掃描／壞字型 PDF） | ⬜ 待做 |
| 表6 徵收土地宗地市價估計表 | ⬜ 待做（賠償金真正的出口） |

**三層檢核的格數**：官方範本一案共比對 77 格——第一層 28 格（表1 的量測值 vs 所填等級）、
第二層 28 格（表1 → 表5-2）、第三層 21 格（表4 的 19 個差異率 + 區域因素調整率 + 合計）。
`/api/review` 會一併回報 `checked` 格數；若換一份規則集而某些細項沒有規則，
那些項目會列在 `not_checkable` 並說明原因，不會靜靜跳過然後顯示「全部通過」。

## 五個寫程式時容易踩的坑

全部是實測踩到的，也都寫成了測試。

**1. 欄位定位只能靠框線與座標，不能靠文字順序。**
範本表4 的「9深度(M)」標籤在 y=149.1，它那一列的值（23 / 16 / 1.00%）在 y=145.8，
差 3.3pt；`pdftotext -layout` 會把這種偏移印成串行。全域 y 分群也不行——
最小列距 3.3pt 與相鄰列距 6.6pt 太接近，任何單一容差都會切錯或併錯。

**2. 分欄要用「單一邊最大跨距」，不能用累計長度。**
同一條欄界常被畫成多個 rect，累計後會和被畫很多次的欄內子分隔線混在一起。
範本表4 實測：欄界最小跨距 247pt、欄內子分隔線最大 105pt。
另外三張表的畫法不同——表1 / 表4 有 line 物件（96 / 164 條），
**表5-2 一條 line 都沒有、只有 140 個 rect**，所以兩者都要收。

**3. 座標與 cell 網格兩種取值方式都要留。**
表4 用座標（欄內有子分隔線，摘要列與資料列排版不同）；
表5-2 與表1 用網格（細項名折成 2–3 行，值落在中間那一行）。
硬要統一成一種，另一張表就會爛掉。

**4. 表1 的等級可能落在標籤的下一列。**
跨列儲存格的文字畫在垂直置中處，會被切到相鄰網格列——
「市場」標籤在 r31、等級在 r32；「廢棄物處理」標籤在 r18、等級在 r19。
而且同一列左右面板各有一組等級（r14 左邊交流道 5/5、右邊殯葬 5/5），
取值必須分面板。

**5. 級數不一定是 5。**
都市計畫內外、有無禁止建築、有無限制建築都是 **2 級**。
把 5 寫死會讓這三項的等級語意整個錯掉。

**6.「區段內有」不能用距離 0 表示。**
區域因素有 9 個細項的最優級是「區段內有」而不是某個距離，而 0 也落在下一級的
「未滿500m」裡——用 0 表示會讓最優級永遠取不到，錯誤還剛好落在「差一級」
這種最難用眼睛看出來的地方。它是一種級距語意（`in_segment`），不是特殊數值。

**7. 重繪書表時，靜態文字要畫在「基線」而不是 bbox 底部。**
用 bbox 底部畫，整頁會下移約 2pt，而且不同字級的位移量不同——
「(元/M²)」的上標 2 會脫離本文，讓辨識器再也找不到那個欄位標籤。
基線在 pdfplumber 的 char `matrix` 平移項裡。

**8. 字寬會因字型而異，辨識器不能假設標籤剛好是一個 word。**
原檔的標楷體子集把 `M` 畫成全形（6.83pt），系統字型是半形（3.84pt），
於是 `M` 與上標 `2` 之間多出 3.0pt 空隙，正好踩到 pdfplumber 切詞的容差，
標籤被切成兩個 word。修的是辨識器（`find_label` 會把同一列相鄰的 word 接起來比對），
不是遷就渲染——換一家機關產的 PDF 一樣會遇到。

**9. Windows 上 uvicorn 的殘留子行程會佔著埠。**
`uvicorn[standard]` 會開 multiprocessing 子行程；父行程被殺掉後子行程仍握著
socket，新的 uvicorn 綁不上 8000 卻只在 log 裡留一行 `[Errno 10048]`，
瀏覽器則表現成「`/api/review` 被 CORS 擋掉」——因為打到的是舊 process。
用 `Get-NetTCPConnection -LocalPort 8000` 找不到擁有者時，
改用 `Get-CimInstance Win32_Process` 找 `--multiprocessing-fork` 的那個子行程。

## 一個已知的合規缺口

金山區商業用地個別因素「道路種類」自訂表最大修正幅度 **8%**，
超出內政部附件25 規定的商業用地上限 **5%**。

validator 只發 WARN、**不自動修正**——因為 Golden Case 的 +2.00% 正是用
超標的 step=2.0 算出來的，自動夾到 5% 會變成 +1.25%，反而重現不出官方答案。
合規問題應回報地政局，不是偷偷改數字。細節見 [kernel/README.md](kernel/README.md)。
