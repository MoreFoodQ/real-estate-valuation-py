# 競賽限制（違反可能影響資格）

2026 新北市 AI 智慧城市黑客松決賽，組別 `地政team2`。
競賽期間 2026/9/12–9/13，AWS 環境僅 9/12 08:00 – 9/13 13:00 可用。

完整資訊見 `docs/COMPETITION_BRIEF.md`：

#[[file:docs/COMPETITION_BRIEF.md]]

---

## 不可違反的硬規定

### 資料
- **不得放入個人資料**及其他 12 類敏感資料。這個系統處理查估書表，裡面有地號
  與路名 —— 一律只用官方範本 `docs/official/real-estate-valuation/查估書表範本.pdf`，
  **不要放真實案件**。
- 程式碼與 commit **不得含任何憑證**（AWS Access Key、API Token、密碼）。
  `docs/competition/ACCESS.local.md` 存有競賽 Access Code，根目錄 `.gitignore`
  已用 `*.local.md` 排除，不要改動這條。

### 部署
- 區域限 **`us-east-1`** 或 **`us-west-2`**
- **AWS App Runner 不在白名單**，後端請用 Lambda / ECS / Elastic Beanstalk
- S3 Bucket 不可公開，要搭 CloudFront
- EC2 Security Group 不可對外全開；RDS / EMR 不可啟用公開存取
- **EC2 沒有 GPU 可用**（G、VT、P 家族配額皆為 0 vCPU）。Standard 家族 256 vCPU
  充裕，本系統是純 CPU 的，夠用。

### AI 模型
- 只能用 **Amazon Bedrock** 或 **SageMaker AI** 提供的基礎模型，不可接外部 API
- Bedrock **每秒最多 1 個請求（1 RPS）**，設計上要避免多輪即時互動
- 只申請專案直接需要的模型，不用的要撤銷存取權

### Kiro
- **`/.kiro` 必須存在於專案根目錄**，展示 specs、hooks、steering 的使用情況
- **不得將 `/.kiro` 或其子資料夾加入 `.gitignore`**

---

## 部署時要先解決的技術問題

後端產出的書表存在 `tempfile.gettempdir()/valuation-forms/<token>/`
（`api/main.py` 的 `FORMS_DIR`），服務重啟就消失。

若部署為 **Lambda**，每次呼叫可能落在不同執行環境，`POST /api/forms` 產表後
`GET /api/forms/{token}/{filename}` 會找不到檔案。**必須改存 S3。**

## Demo 風險

簡報使用主辦單位的電腦投影，且 AWS 環境在 9/13 13:00 關閉（與交件同時）。
上台時可能既沒有自己的筆電也沒有雲端環境。

**優先錄製 demo 影片**，不要把 demo 綁在只能跑 localhost 的環境上。
