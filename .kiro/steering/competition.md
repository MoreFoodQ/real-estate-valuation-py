# 部署與資料的硬性限制

本專案的執行環境有幾條不可協商的限制，來自環境提供方的規範。
動到部署、資料或模型選擇之前先看這裡。

---

## 不可違反的硬規定

### 資料
- **不得放入個人資料**及其他 12 類敏感資料。這個系統處理查估書表，裡面有地號
  與路名 —— 一律只用官方範本 `docs/official/real-estate-valuation/查估書表範本.pdf`，
  **不要放真實案件**。
- 程式碼與 commit **不得含任何憑證**（AWS Access Key、API Token、密碼）。
  憑證一律不寫入任何檔案，需要時直接貼進終端機。根目錄 `.gitignore` 已排除
  `*.local.md` 與 `*.local` 作為後備防線，不要改動這兩條。

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

### 專案設定
- **`/.kiro` 必須留在專案根目錄**，記錄 steering 與 hooks 的設定
- **不得將 `/.kiro` 或其子資料夾加入 `.gitignore`**

---

## 部署時要先解決的技術問題

後端產出的書表存在 `tempfile.gettempdir()/valuation-forms/<token>/`
（`api/main.py` 的 `FORMS_DIR`），服務重啟就消失。

若部署為 **Lambda**，每次呼叫可能落在不同執行環境，`POST /api/forms` 產表後
`GET /api/forms/{token}/{filename}` 會找不到檔案。**必須改存 S3。**

## 示範環境的風險

雲端環境有使用期限，到期後就沒有可運行的部署。示範時也不一定能用自己的電腦。

**優先錄製操作影片**，不要把示範綁在只能跑 localhost 的環境上。
