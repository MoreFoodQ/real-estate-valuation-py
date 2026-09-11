"""審查模式：把估價師填的值與引擎重算的值逐格比對。

三層對應作業手冊的官方審查重點（`土地徵收補償市價查估作業手冊` 印刷頁 11–13）：

- 第一層 表1 內部：量測值與所填等級是否相符
- 第二層 表1 → 表5-2：審查重點第 vi 項「修正細項優劣等級**與各該地價區段
  勘查表所載內容一致**」
- 第三層 表5-2 → 表4：審查重點第 vii 項「區域因素調整百分率**與影響地價
  區域因素總修正數相符**」

第一層最容易被忽略卻最有價值：錯在源頭會一路連鎖到賠償金，
而人工最難抓的就是這層（得拿著尺與基準表一項一項核）。

能查到什麼取決於規則集補到哪裡。區域因素 28 項、個別因素 19 項都已編碼完成，
所以三層目前都是完整的（官方範本共查 77 格）。若換一份規則集而某些細項沒有規則，
那些項目會列在 `not_checkable` 裡並說明原因，並反映在 `checked` 的格數上——
不會假裝「全部通過」。
"""

from __future__ import annotations

from typing import Any

from parser.survey import survey_value

from .kernel_api import RuleSet, appraise_table4, classify


def review(
    tables: dict[str, Any],
    rs_individual: RuleSet,
    rs_regional: RuleSet | None,
) -> dict[str, Any]:
    layers = {
        "table1_internal": [],
        "table1_to_table5_2": [],
        "table5_2_to_table4": [],
    }
    # 查了幾格。沒有這個數字，「相符」就只是一句沒有份量的話——
    # 少查 23 項的「相符」和全查的「相符」在畫面上不該長得一樣。
    checked = {"table1_internal": 0, "table1_to_table5_2": 0, "table5_2_to_table4": 0}
    not_checkable: list[dict[str, Any]] = []

    t1 = tables.get("表1")
    t52 = tables.get("表5-2")
    t4 = tables.get("表4")

    if t1 and rs_regional is not None:
        layers["table1_internal"], skipped, checked["table1_internal"] = (
            _check_table1_internal(t1, rs_regional)
        )
        not_checkable.extend(skipped)
    elif t1:
        not_checkable.append(
            {
                "layer": "table1_internal",
                "reason": "未提供區域因素規則集，無法由量測值反推等級",
            }
        )

    if t1 and t52:
        layers["table1_to_table5_2"] = _check_table1_vs_table5_2(t1, t52)
        checked["table1_to_table5_2"] = len(t52["benchmark_grades"])
    else:
        not_checkable.append(
            {"layer": "table1_to_table5_2", "reason": "缺表1 或表5-2，無法跨表比對"}
        )

    price_impact: dict[str, Any] | None = None
    if t4:
        findings, price_impact, checked["table5_2_to_table4"] = _check_table4(
            t4, t52, rs_individual
        )
        layers["table5_2_to_table4"] = findings
    else:
        not_checkable.append({"layer": "table5_2_to_table4", "reason": "缺表4"})

    total = sum(len(v) for v in layers.values())
    return {
        "verdict": "mismatch" if total else "match",
        "finding_count": total,
        "checked": checked,
        "checked_total": sum(checked.values()),
        "layers": layers,
        "not_checkable": not_checkable,
        "price_impact": price_impact,
    }


# ---------- 第一層：表1 內部 ----------


def _check_table1_internal(
    t1: dict[str, Any], rs: RuleSet
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    findings: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    checked = 0

    for factor_id, cell in t1["grades"].items():
        if factor_id not in rs.factor_ids:
            skipped.append(
                {
                    "layer": "table1_internal",
                    "factor_id": factor_id,
                    "reason": "規則集尚未包含此細項（區域因素目前 %d/28）"
                    % len(rs.factor_ids),
                }
            )
            continue

        factor = rs[factor_id]
        survey = t1["surveys"].get(factor_id) or {}
        got = survey_value(survey, factor.classifier.get("direction", ""))
        if got is None:
            skipped.append(
                {
                    "layer": "table1_internal",
                    "factor_id": factor_id,
                    "reason": "表1 這一格無法判讀成可分級的值（原文：%s）"
                    % (survey.get("raw") or "").replace("\n", " / "),
                }
            )
            continue

        value, how = got
        try:
            grade = classify(factor, value)
        except ValueError as e:
            # 級距沒有涵蓋這個值（最常見的是「無」而條文未載「或無」）。
            # 這是規則的缺口，不是案件的錯，所以列為查不動而不是不符。
            skipped.append(
                {
                    "layer": "table1_internal",
                    "factor_id": factor_id,
                    "reason": "%s；%s" % (how, e),
                }
            )
            continue

        checked += 1
        if cell["grade"] != grade.grade:
            findings.append(
                {
                    "factor_id": factor_id,
                    "filed": {"grade": cell["grade"]},
                    "computed": {"grade": grade.grade, "label": grade.label},
                    "basis": "%s；%s" % (how, grade.reason),
                }
            )
    return findings, skipped, checked


# ---------- 第二層：表1 → 表5-2 ----------


def _check_table1_vs_table5_2(
    t1: dict[str, Any], t52: dict[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for factor_id, cell in t52["benchmark_grades"].items():
        source = t1["grades"].get(factor_id)
        if source is None:
            findings.append(
                {
                    "factor_id": factor_id,
                    "filed": {"grade": cell["grade"], "label": cell["label"]},
                    "computed": None,
                    "basis": "表5-2 有這個細項，但表1 找不到對應欄位",
                }
            )
            continue
        if source["grade"] != cell["grade"]:
            findings.append(
                {
                    "factor_id": factor_id,
                    "filed": {"grade": cell["grade"], "label": cell["label"]},
                    "computed": {"grade": source["grade"]},
                    "basis": "表1「%s」所載等級為 %s（審查重點第 vi 項要求兩表一致）"
                    % (source["label_in_form"], source["grade"]),
                }
            )
    return findings


# ---------- 第三層：表5-2 → 表4，以及表4 內部重算 ----------


def _check_table4(
    t4: dict[str, Any], t52: dict[str, Any] | None, rs: RuleSet
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
    findings: list[dict[str, Any]] = []
    checked = 0
    result = appraise_table4(rs, t4)

    for filed, computed in zip(t4["comparables"], result.comparables):
        idx = filed["index"]

        # 審查重點第 vii 項：表4 的區域因素調整百分率必須等於表5-2 的總修正數。
        if t52 is not None:
            source = next(
                (c for c in t52["comparables"] if c["index"] == idx), None
            )
            checked += 1
            if source is not None and source["filed_total"] != filed[
                "regional_adjustment_pct"
            ]:
                findings.append(
                    {
                        "factor_id": "table4.regional_adjustment_pct",
                        "comparable_index": idx,
                        "filed": filed["regional_adjustment_pct"],
                        "computed": source["filed_total"],
                        "basis": "表5-2 影響地價區域因素總修正數為 %s%%"
                        % source["filed_total"],
                    }
                )

        by_id = {row.factor_id: row for row in computed.rows}
        for factor_id, pct in filed["filed_corrections"].items():
            row = by_id.get(factor_id)
            if row is None:
                continue
            checked += 1
            if row.correction.pct != pct:
                findings.append(
                    {
                        "factor_id": factor_id,
                        "comparable_index": idx,
                        "filed": pct,
                        "computed": row.correction.pct,
                        "basis": " / ".join(
                            [
                                row.benchmark_grade.reason,
                                row.comparable_grade.reason,
                                row.correction.reason,
                            ]
                        ),
                        "source_page": row.correction.source_page,
                    }
                )

        checked += 1
        if filed.get("individual_total_pct") != computed.individual_total_pct:
            findings.append(
                {
                    "factor_id": "table4.individual_total_pct",
                    "comparable_index": idx,
                    "filed": filed.get("individual_total_pct"),
                    "computed": computed.individual_total_pct,
                    "basis": "個別因素合計＝各項差異率直接相加（作業手冊 p.53）",
                }
            )

    filed_price = t4["comparables"][0].get("trial_price")
    price_impact = {
        "filed": filed_price,
        "computed": result.benchmark_comparison_price,
        "benchmark_land_price": result.benchmark_land_price,
        "diff_per_sqm": None
        if filed_price is None
        else result.benchmark_comparison_price - filed_price,
    }
    return findings, price_impact, checked
