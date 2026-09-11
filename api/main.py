"""FastAPI 薄殼。

這一層只做 JSON 進出與檔案接收，**沒有任何計算邏輯**：
辨識在 `parser/`、計算在 `kernel/`。這條分界是刻意的——
demo 的主論述是「每個數字都能指回官方文件」，一旦 API 層開始自己算，
那條追溯鏈就斷在這裡了。

回應格式與端點規格見 `api/CONTRACT.md`（以前端既有的 axiosService 為準）。
啟動：`python -m uvicorn api.main:app --reload --port 8000`
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import paths
from parser import table1, table4, table5_2
from parser.detect import detect_table
from parser.extract import load_pages

from pdfform.fill import FORM_CODES
from pdfform.forms import FILE_STEMS, build_forms

from .envelope import install_error_handlers, ok
from .kernel_api import (
    RULES_DIR,
    appraise_table4,
    check_ruleset,
    classify,
    load_ruleset,
    lookup,
    validation_errors,
)
from .review import review

PARSERS = {"表1": table1.parse, "表5-2": table5_2.parse, "表4": table4.parse}

DEFAULT_INDIVIDUAL = "jinshan_commercial_individual"
DEFAULT_REGIONAL = "jinshan_commercial_regional"

app = FastAPI(title="不動產估價案件審查 API", version="0.1.0")

# 前端攔截器把「請求已發出但沒收到回應」一律記成網路錯誤，
# CORS 沒開會表現成看不出原因的失敗，所以這條要先設對。
#
# 用 regex 而不是寫死 5173：vite 遇到埠被占用會自動往上找（實測掉到 5174），
# 這時寫死的白名單會讓整個前端突然連不上，而錯誤訊息完全看不出是 CORS。
# 這是開發用設定；上線要換成明確的來源清單。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
install_error_handlers(app)


@app.get("/api/rulesets")
def list_rulesets() -> dict[str, Any]:
    """列出可用規則集。Demo 現場抽換不同行政區的基準表要用這個。

    `status` 必須誠實回報 partial：前端要能顯示「這份規則集只補到 5/28，
    其餘細項算不出修正率」，而不是讓使用者以為全部都查過了。
    """
    items = []
    for path in sorted(RULES_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if "factors" not in raw:
            continue  # moi_caps.json 是上限表，不是規則集
        scope = raw.get("scope") or {}
        items.append(
            {
                "ruleset_id": raw.get("ruleset_id", path.stem),
                "kind": "regional" if "regional" in path.stem else "individual",
                "district": scope.get("district"),
                "land_use": scope.get("land_use"),
                "status": raw.get("status"),
                "completeness": raw.get("completeness"),
                "factor_count": len(raw["factors"]),
            }
        )
    return ok({"rulesets": items})


@app.post("/api/parse")
async def parse_forms(file: UploadFile = File(...)) -> dict[str, Any]:
    """上傳查估書表 PDF，逐頁判斷表別並辨識。

    缺表不算錯誤——官方可能分檔送，或只送需要複查的那一張。
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(422, "只接受 PDF 檔，收到的是：%s" % file.filename)

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        pages = load_pages(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    page_map = [{"page": p.number, "table": detect_table(p)} for p in pages]

    tables: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    warnings: list[dict[str, Any]] = []
    case_id: str | None = None

    for page in pages:
        code = detect_table(page)
        if code is None or code in tables:
            continue
        parsed = PARSERS[code](page)
        tables[code] = parsed.to_dict()
        for key, source in parsed.provenance.to_dict().items():
            provenance["%s.%s" % (code, key)] = source
        for w in getattr(parsed, "warnings", []):
            warnings.append({**w, "table": code})
        case_id = case_id or getattr(parsed, "case_id", None)

    if not tables:
        raise HTTPException(400, "這份 PDF 裡找不到任何可辨識的查估書表（表1／表5-2／表4）")

    return ok(
        {
            "case_id": case_id,
            "pages": page_map,
            "tables": tables,
            "provenance": provenance,
            "warnings": warnings,
        }
    )


@app.post("/api/compute")
def compute(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """依規則集重算表4 全鏈路，回傳結果與依據鏈。

    `corrections[].basis` 就是 demo 的主論述：每個修正率都指得回
    「量測值 → 基準表哪一列 → 矩陣哪一格 → 來源頁」。
    """
    tables = _require_tables(payload)
    if "表4" not in tables:
        raise HTTPException(400, "計算需要表4（比較法調查估價表），payload 裡沒有")

    rs = _load(payload.get("ruleset_individual") or DEFAULT_INDIVIDUAL)
    result = appraise_table4(rs, tables["表4"])

    comparables = []
    for c in result.comparables:
        comparables.append(
            {
                "index": c.index,
                "date_pct": c.date_pct,
                "regional_pct": c.regional_pct,
                "individual_total_pct": c.individual_total_pct,
                "abs_sum_pct": c.abs_sum_pct,
                "similarity_label": c.similarity,
                "weight_pct": c.weight_pct,
                "trial_price": c.trial_price,
                "corrections": [
                    {
                        "factor_id": row.factor_id,
                        "label": row.label,
                        "table4_row": row.table4_row,
                        "benchmark": {
                            "value": row.benchmark_value,
                            "grade": row.benchmark_grade.grade,
                            "label": row.benchmark_grade.label,
                            "reason": row.benchmark_grade.reason,
                        },
                        "comparable": {
                            "value": row.comparable_value,
                            "grade": row.comparable_grade.grade,
                            "label": row.comparable_grade.label,
                            "reason": row.comparable_grade.reason,
                        },
                        "correction_pct": row.correction.pct,
                        "basis": row.correction.reason,
                        "source_page": row.correction.source_page,
                    }
                    for row in c.rows
                ],
            }
        )

    return ok(
        {
            "ruleset_individual": rs.ruleset_id,
            "comparables": comparables,
            "benchmark_comparison_price": result.benchmark_comparison_price,
            "benchmark_land_price_rounded": result.benchmark_land_price,
            # 「算得出來但需要人工確認」的事項（例如權重合計不是 100%）。
            # 不阻擋計算，但不能靜默吞掉——審查工具的可信度建立在
            # 「有疑慮就說出來」，與 review 的 not_checkable 同一個原則。
            "warnings": result.warnings,
        }
    )


@app.post("/api/review")
def review_case(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """審查模式：三層逐格比對，並算出賠償金差額。"""
    tables = _require_tables(payload)
    rs_ind = _load(payload.get("ruleset_individual") or DEFAULT_INDIVIDUAL)
    rs_reg = None
    if payload.get("ruleset_regional") is not False:
        rs_reg = _load(payload.get("ruleset_regional") or DEFAULT_REGIONAL)
    return ok(review(tables, rs_ind, rs_reg))


# ---------- 共用 ----------


def _require_tables(payload: dict[str, Any]) -> dict[str, Any]:
    tables = payload.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise HTTPException(422, "payload 需要 tables 欄位，內容為 /api/parse 的回傳結果")
    return tables


def _load(ruleset_id: str):
    """載入規則集，並在使用前跑一次結構自檢。

    `check_ruleset()` 會抓級距缺口／重疊、矩陣非反對稱、max_range 與矩陣不符
    等 12 類問題。它原本只在 kernel/demo.py 與測試裡被呼叫，執行期完全沒有
    防線——壞掉的規則集會靜默載入並產出看起來正常的結果。

    實測：把某細項的級距挖掉一級，`check_ruleset` 報 2 個 ERROR，但 review()
    仍回報「查 77 格、0 處不符」，因為官方範本剛好沒踩到那個洞。
    規則集有缺口時不會主動被發現，只有踩到才會——所以這道檢查必須在入口做。
    """
    try:
        rs = load_ruleset(ruleset_id)
    except FileNotFoundError:
        available = sorted(p.stem for p in RULES_DIR.glob("*.json"))
        raise HTTPException(
            404, "找不到規則集 %r，可用的有：%s" % (ruleset_id, "、".join(available))
        ) from None

    bad = validation_errors(check_ruleset(rs))
    if bad:
        raise HTTPException(
            500,
            "規則集 %r 結構有誤，共 %d 項，不予採用（避免算出錯的補償金）：\n%s"
            % (ruleset_id, len(bad), "\n".join(str(f) for f in bad[:10])),
        )
    return rs


# 產出的書表暫存在這裡，每次啟動清空。書表是衍生物、不是資料——
# 重跑一次就有，沒有保存的必要，留著反而要處理保存期限與個資。
FORMS_DIR = Path(tempfile.gettempdir()) / "valuation-forms"


@app.post("/api/forms")
async def generate_forms(file: UploadFile = File(...)) -> dict[str, Any]:
    """上傳查估書表 PDF，產出三張**填好的**官方格式書表。

    回傳的是檔案清單與下載連結，不是檔案本身——回應信封規定 body 必須是
    `{data, error}`，二進位塞不進去。這與前端既有的 `UploadedResponse`
    （id / link）形狀一致。
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(422, "只接受 PDF 檔，收到的是：%s" % file.filename)

    token = uuid.uuid4().hex
    work = FORMS_DIR / token
    work.mkdir(parents=True, exist_ok=True)
    src = work / "input.pdf"
    src.write_bytes(await file.read())

    try:
        written = build_forms(
            src,
            work,
            # 走 _load 而不是 load_ruleset：產表也要吃結構自檢，
            # 否則壞掉的規則集會被填進「可交件」的官方書表裡。
            regional=_load(DEFAULT_REGIONAL),
            individual=_load(DEFAULT_INDIVIDUAL),
            appraise=appraise_table4,
            classify=classify,
            lookup=lookup,
        )
    except ValueError as e:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(400, str(e)) from None

    return ok(
        {
            "id": token,
            "files": [
                {
                    "table": code,
                    "filename": written[code].name,
                    "size": written[code].stat().st_size,
                    "link": "/api/forms/%s/%s" % (token, written[code].name),
                }
                for code in FORM_CODES
                if code in written
            ],
        }
    )


@app.get("/api/forms/{token}/{filename}")
def download_form(token: str, filename: str) -> FileResponse:
    """下載產出的書表。這支端點回傳的是 PDF 本身，不是信封——

    檔案下載本來就不適用 JSON 信封，前端也是用 `link` 直接開，不走攔截器。
    """
    if not token.isalnum() or "/" in filename or "\\" in filename:
        raise HTTPException(400, "路徑不合法")
    if filename not in {"%s.pdf" % stem for stem in FILE_STEMS.values()}:
        raise HTTPException(404, "沒有這個檔名：%s" % filename)

    path = FORMS_DIR / token / filename
    if not path.exists():
        raise HTTPException(404, "檔案已不存在，請重新產出（產出的書表只暫存到服務重啟）")
    return FileResponse(path, media_type="application/pdf", filename=filename)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return ok({"status": "ok", "doc_dir": str(paths.DOC_DIR)})
