"""決定三張書表的每一格要填什麼。

分兩種來源，這個分界是整個系統的論述核心：

- **輸入欄位**（地號、量測值、正常單價、交易日期、備註）原封不動搬過來。
  這些是現場調查與實價登錄的事實，系統不該碰。
- **計算欄位**（等級、級數、修正率、小計、合計、試算價格、比較價格）
  一律由 kernel 依評價基準明細表算出來，**不採用原檔的值**。

所以產出的書表裡，凡是「該算的」都是算的。如果原檔某一格填錯了，
產出的表會是對的那個值——這也是為什麼同一份輸入可以同時餵給審查模式。

一個誠實的限制：表5-2 需要比準地與比較標的**兩個區段**的勘查表，
而官方範本只有一張表1（兩者同區段）。所以比較標的的區域因素等級目前
沿用比準地的，修正率因此全為 0。跨區段案件要等第二張表1 才算得出來。
"""

from __future__ import annotations

from typing import Any

from parser.survey import survey_value

FORM_CODES = ("表1", "表5-2", "表4")


def _pct(value: Any, suffix: str = "") -> str:
    if value is None:
        return ""
    return "%.2f%s" % (float(value), suffix)


def _num(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    f = float(value)
    return "{:,.0f}".format(f) if f == int(f) and abs(f) >= 1000 else ("%g" % f)


def build_values(
    tables: dict[str, Any],
    regional: Any,
    individual: Any,
    appraise,
    classify,
    lookup,
) -> dict[str, dict[str, str]]:
    """回傳 `{表別: {欄位路徑: 要畫的文字}}`。

    kernel 的函式以參數傳入而不是 import，讓 pdfform 不直接依賴 kernel——
    相依方向由 api 那一層決定（見 `api/kernel_api.py`）。
    """
    out: dict[str, dict[str, str]] = {code: {} for code in FORM_CODES}

    t1 = tables.get("表1")
    t52 = tables.get("表5-2")
    t4 = tables.get("表4")

    grades: dict[str, Any] = {}
    if t1 is not None:
        grades = _fill_table1(t1, regional, classify, out["表1"])
    if t52 is not None:
        _fill_table5_2(t52, grades, regional, lookup, out["表5-2"])
    if t4 is not None:
        _fill_table4(t4, individual, appraise, out["表4"])

    return out


# ---------- 表1 ----------


def _fill_table1(t1, rs, classify, values: dict[str, str]) -> dict[str, Any]:
    """只填等級與級數，量測值原封不動留在版面上。

    回傳算出來的等級，供表5-2 使用——書表的資料流就是這個方向
    （表1 → 表5-2 → 表4），產表也照著走，不從表5-2 反抄。
    """
    graded: dict[str, Any] = {}
    for factor_id, cell in t1["grades"].items():
        survey = t1["surveys"].get(factor_id) or {}
        # 量測值不填：見 forms.INPUT_ONLY_PREFIXES，它們留在靜態層。
        if factor_id not in rs.factor_ids:
            continue
        factor = rs[factor_id]
        got = survey_value(survey, factor.classifier.get("direction", ""))
        if got is None:
            continue
        try:
            grade = classify(factor, got[0])
        except ValueError:
            continue  # 級距涵蓋不到，留白比填一個猜的值好
        graded[factor_id] = grade
        values["grades.%s.grade" % factor_id] = str(grade.grade)
        values["grades.%s.grade_count" % factor_id] = str(factor.grade_count)
    return graded


# ---------- 表5-2 ----------


def _fill_table5_2(t52, graded, rs, lookup, values: dict[str, str]) -> None:
    comparables = t52.get("comparables") or []
    subtotals: dict[str, dict[str, float]] = {}

    for factor_id, grade in graded.items():
        values["benchmark_grades.%s.grade" % factor_id] = str(grade.grade)
        values["benchmark_grades.%s.label" % factor_id] = grade.label

    for c in comparables:
        idx = c["index"]
        acc: dict[str, float] = {}
        for group in t52.get("groups") or []:
            for factor_id in group["factor_ids"]:
                grade = graded.get(factor_id)
                if grade is None:
                    continue
                # 同區段：比較標的的區域條件與比準地相同。跨區段案件需要
                # 第二張表1，屆時這裡改成用該區段自己的等級。
                cg = grade.grade
                values["comparables[%d].grades.%s.grade" % (idx, factor_id)] = str(cg)
                values["comparables[%d].grades.%s.label" % (idx, factor_id)] = grade.label
                pct = float(lookup(rs[factor_id], grade.grade, cg).pct)
                values["comparables[%d].filed_corrections.%s" % (idx, factor_id)] = _pct(pct)
                acc[group["label"]] = acc.get(group["label"], 0.0) + pct

        for group in t52.get("groups") or []:
            label = group["label"]
            values["comparables[%d].filed_subtotals.%s" % (idx, label)] = _pct(
                acc.get(label, 0.0), " ％"
            )
        values["comparables[%d].filed_total" % idx] = _pct(sum(acc.values()), " ％")
        subtotals[str(idx)] = acc


# ---------- 表4 ----------


def _fill_table4(t4, rs, appraise, values: dict[str, str]) -> None:
    # 條件欄照抄：那是宗地的事實，不是算出來的。
    for side, prefix in ((t4["benchmark"], "benchmark"), *(
        (c, "comparables[%d]" % c["index"]) for c in t4["comparables"]
    )):
        for factor_id, value in side["facts"].items():
            label = side.get("fact_labels", {}).get(factor_id)
            values["%s.facts.%s" % (prefix, factor_id)] = label or _num(value)
        values["%s.parcel" % prefix] = side.get("parcel") or ""
        values["%s.segment" % prefix] = side.get("segment") or ""

    for c in t4["comparables"]:
        prefix = "comparables[%d]" % c["index"]
        values["%s.transaction_date" % prefix] = c.get("transaction_date") or ""
        values["%s.normal_unit_price" % prefix] = _num(c.get("normal_unit_price"))
        values["%s.date_adjustment_pct" % prefix] = _pct(c.get("date_adjustment_pct"), "%")
        values["%s.date_adjusted_unit_price_displayed" % prefix] = _num(
            c.get("date_adjusted_unit_price_displayed")
        )
        values["%s.regional_adjustment_pct" % prefix] = _pct(
            c.get("regional_adjustment_pct"), "%"
        )

    result = appraise(rs, t4)
    for computed in result.comparables:
        prefix = "comparables[%d]" % computed.index
        for row in computed.rows:
            values["%s.filed_corrections.%s" % (prefix, row.factor_id)] = _pct(
                row.correction.pct, "%"
            )
        values["%s.individual_total_pct" % prefix] = _pct(computed.individual_total_pct, "%")
        values["%s.abs_sum_pct" % prefix] = _pct(computed.abs_sum_pct, "%")
        values["%s.similarity_label" % prefix] = computed.similarity
        values["%s.trial_price" % prefix] = _num(computed.trial_price)
        # 權重原檔寫「100%」不是「100.00%」，沿用原檔寫法
        values["%s.weight_pct" % prefix] = "%g%%" % float(computed.weight_pct)

    values["benchmark_comparison_price"] = _num(result.benchmark_comparison_price)
