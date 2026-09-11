"""格式變異容忍度測試。

`audit.py` 測的是「值」的變異（畸形數值、缺表、換規則集）。這支測的是
「結構」的變異：書表怎麼切檔、欄位位置移動、出現沒收錄的細項名。

最重要的不是「能不能讀到」，而是**讀不到的時候會怎麼失敗**：

  大聲失敗  拋例外或發警告，欄位留空 → 安全，看得出要調哪裡
  安靜失敗  照樣算出一個看起來合理的答案 → 危險，審查結論不可信

每個案例都印出判定，`SILENT` 一出現就要當成缺陷處理。

用法：python -m stress.variants
"""

from __future__ import annotations

import io
from typing import Any, Callable

import paths
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

import parser.table1 as t1
import parser.table4 as t4
import parser.table5_2 as t52
from api.main import app
from parser.detect import detect_table
from parser.extract import load_pages

RULESET_PREFIX = "jinshan_commercial"

LOUD = "LOUD "
SILENT = "SILENT"
OK = "OK   "


def _line(tag: str, title: str, detail: str) -> None:
    print("%s %-34s %s" % (tag, title, detail))


# ---------- A. 檔案怎麼切 ----------


def group_a(client: TestClient) -> dict[str, Any]:
    """三張表分成三個檔逐一上傳，再把結果合起來審查。

    `detect_table` 依頁首標題判斷而不依頁碼，所以理論上支援任意切法。
    這組驗證整條 API 路徑（不只 parser）真的撐得住。
    """
    print("\n── A. 檔案切法 ──")
    single = {
        "表1": paths.ROOT / "stress" / "tampered" / "tampered-grade-table1-survey.pdf",
        "表5-2": paths.ROOT / "stress" / "tampered" / "tampered-grade-table5_2-regional.pdf",
        "表4": paths.ROOT / "stress" / "tampered" / "tampered-grade-table4-comparison.pdf",
    }
    merged: dict[str, Any] = {}
    for code, path in single.items():
        if not path.exists():
            _line(LOUD, "A1 只含 %s 的單檔" % code, "測資不存在，先跑 stress.make_tampered")
            continue
        with open(path, "rb") as fh:
            r = client.post(
                "/api/parse", files={"file": (path.name, fh, "application/pdf")}
            )
        if r.status_code != 200:
            _line(LOUD, "A1 只含 %s 的單檔" % code, "HTTP %d" % r.status_code)
            continue
        data = r.json()["data"]
        merged.update(data["tables"])
        _line(OK, "A1 只含 %s 的單檔" % code, "辨識出 %s" % list(data["tables"]))
    return merged


def group_a_review(client: TestClient, merged: dict[str, Any]) -> None:
    """分開上傳的結果合起來，審查格數應與一次送三表相同。"""

    def review(tables: dict[str, Any]) -> dict[str, Any] | None:
        r = client.post(
            "/api/review",
            json={"tables": tables, "ruleset_prefix": RULESET_PREFIX},
        )
        return r.json()["data"] if r.status_code == 200 else None

    full = review(merged)
    if full:
        _line(
            OK,
            "A2 三檔結果合併後審查",
            "查核 %d 格，不符 %d 處" % (full["checked_total"], full["finding_count"]),
        )
    else:
        _line(LOUD, "A2 三檔結果合併後審查", "審查失敗")

    for code in ("表4", "表1", "表5-2"):
        if code not in merged:
            continue
        one = review({code: merged[code]})
        if one is None:
            _line(LOUD, "A3 只有 %s 時降級" % code, "審查失敗（應該要能降級）")
            continue
        empty = [k for k, v in one["checked"].items() if v == 0]
        _line(
            OK,
            "A3 只有 %s 時降級" % code,
            "查核 %d 格，跳過 %d 層" % (one["checked_total"], len(empty)),
        )


def group_a_junk(client: TestClient) -> None:
    """完全無關的 PDF 應該乾淨地拒絕，不是 500。"""
    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    cv.drawString(100, 700, "not a valuation form")
    cv.save()
    r = client.post(
        "/api/parse", files={"file": ("junk.pdf", buf.getvalue(), "application/pdf")}
    )
    tag = LOUD if 400 <= r.status_code < 500 else SILENT
    _line(tag, "A4 完全無關的 PDF", "HTTP %d" % r.status_code)


# ---------- B. 欄位位置移動 ----------


def _shifted(restore: Callable[[], None], run: Callable[[], tuple[int, int]]) -> tuple[str, str]:
    """跑一個位移情境，回傳 (判定, 說明)。

    位移後仍讀出非空的值＝安靜失敗，因為那些值來自錯誤的格子。
    """
    try:
        total, non_null = run()
    except Exception as exc:  # noqa: BLE001 — 這裡就是要記錄任何例外型別
        return LOUD, "拋 %s：%s" % (type(exc).__name__, str(exc)[:44])
    finally:
        restore()
    if non_null == 0:
        return LOUD, "讀到 %d 項但值全空" % total
    return SILENT, "仍讀出 %d 項非空值，可能取自錯誤的格子" % non_null


def group_b(page1: Any, page52: Any) -> None:
    """把欄索引整體右移一格，模擬書表多了一欄。"""
    print("\n── B. 欄位位置移動 ──")

    original_panels = t1.PANELS

    def run_t1() -> tuple[int, int]:
        t1.PANELS = {
            t1.LEFT: {"grade": (2, 3), "labels": (4,), "values": range(5, 10)},
            t1.RIGHT: {"grade": (11, 12), "labels": (13, 10), "values": range(14, 17)},
        }
        result = t1.parse(page1)
        non_null = sum(1 for v in result.grades.values() if v["grade"] is not None)
        return len(result.grades), non_null

    def restore_t1() -> None:
        t1.PANELS = original_panels

    tag, detail = _shifted(restore_t1, run_t1)
    _line(tag, "B1 表1 欄索引右移一格", detail)

    original_cols = (
        t52.COL_GROUP,
        t52.COL_FACTOR,
        t52.COL_BENCHMARK_GRADE,
        t52.COL_BENCHMARK_LABEL,
    )

    def run_t52() -> tuple[int, int]:
        t52.COL_GROUP, t52.COL_FACTOR = 1, 2
        t52.COL_BENCHMARK_GRADE, t52.COL_BENCHMARK_LABEL = 3, 4
        result = t52.parse(page52)
        non_null = sum(
            1
            for v in result.benchmark_grades.values()
            if v.get("grade") is not None
        )
        return len(result.benchmark_grades), non_null

    def restore_t52() -> None:
        (
            t52.COL_GROUP,
            t52.COL_FACTOR,
            t52.COL_BENCHMARK_GRADE,
            t52.COL_BENCHMARK_LABEL,
        ) = original_cols

    tag, detail = _shifted(restore_t52, run_t52)
    _line(tag, "B2 表5-2 欄索引右移一格", detail)


# ---------- C. 沒收錄的細項名 ----------


def group_c(page1: Any) -> None:
    """對照表加入書表上不存在的細項，模擬換用地類別後項目不同。

    期望：找不到的項目發警告並跳過，不影響其他項。
    """
    print("\n── C. 沒收錄的細項名 ──")
    original = t1.TABLE1_ROWS
    extra = (
        ("灌溉排水設施", t1.LEFT, "regional.agri.irrigation"),
        ("農路寬度", t1.LEFT, "regional.agri.farm_road"),
    )
    try:
        t1.TABLE1_ROWS = original + extra
        result = t1.parse(page1)
        missing = [w for w in result.warnings if w["code"] == "factor_row_not_found"]
        tag = OK if len(result.grades) == len(original) and len(missing) == len(extra) else SILENT
        _line(
            tag,
            "C1 對照表多兩項不存在的細項",
            "讀到 %d 項，%d 則找不到警告" % (len(result.grades), len(missing)),
        )
    finally:
        t1.TABLE1_ROWS = original


# ---------- D. 框線偵測門檻 ----------


def group_d(page4: Any) -> None:
    """表4 的欄界是從框線動態算的，這組看門檻的容忍範圍。"""
    print("\n── D. 框線偵測門檻 ──")
    for span in (100.0, 200.0, 300.0, 400.0, 600.0):
        try:
            edges = t4.column_edges(page4, min_span=span)
        except Exception as exc:  # noqa: BLE001
            _line(LOUD, "D1 min_span=%.0f" % span, "拋 %s" % type(exc).__name__)
            continue
        if len(edges) < 4:
            _line(LOUD, "D1 min_span=%.0f" % span, "只抓到 %d 條欄界，parse 會拋 ValueError" % len(edges))
        else:
            _line(OK, "D1 min_span=%.0f" % span, "抓到 %d 條欄界" % len(edges))


# ---------- 主程式 ----------


def main() -> int:
    print("格式變異容忍度測試")
    print("=" * 62)
    print("LOUD   = 大聲失敗（安全）")
    print("SILENT = 安靜失敗（缺陷，要修）")

    pages = load_pages(paths.require(paths.SAMPLE_FORMS_PDF))
    by_code = {detect_table(p): p for p in pages if detect_table(p)}

    client = TestClient(app)
    merged = group_a(client)
    if merged:
        group_a_review(client, merged)
    group_a_junk(client)

    group_b(by_code["表1"], by_code["表5-2"])
    group_c(by_code["表1"])
    group_d(by_code["表4"])

    print("\n" + "=" * 62)
    print("判讀：只要出現 SILENT 就是缺陷。LOUD 代表失敗看得見，")
    print("      對照 docs/ROBUSTNESS_AUDIT.md 的調整點索引即可定位。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
