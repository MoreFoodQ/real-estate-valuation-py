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

# ---------- 合理性檢查 ----------
#
# 這一組檢查回答的是「這個數字本身合不合理」，與三層檢核的「估價師填得對不對」
# 是兩件事。存在的理由：壓力測試發現單價被誤讀成 -184,763 時，系統會算出
# 補償金 -212,958 並回報「相符」——不是壞掉，是自信地給出錯的答案。
# 那比拋出例外危險得多，因為沒有任何跡象讓人知道要懷疑。
#
# 設計原則沿用 kernel/src/validate.py 對內政部上限的做法：**只警告，不阻擋，
# 不自動修正**。系統若遇到可疑值就拒絕運算，審查員就看不到「這份書表算出來
# 會是什麼」；正確做法是算出來，同時大聲說這個值有問題。判斷權留給人。

# 修正率的合理上限。內政部各細項上限最大 40%（附件24 商業用地都市計畫項），
# 總修正數理論上可以疊加，但單一細項或合計超過 100% 幾乎確定是誤讀。
_PCT_ABS_LIMIT = 100

# 這些欄位是幾何量或金額，必須為正數。
_MUST_BE_POSITIVE = {
    "individual.parcel.area": "面積",
    "individual.parcel.width": "寬度",
    "individual.parcel.depth": "深度",
}


def _num(value: Any) -> float | None:
    """寬鬆轉數字，失敗回 None。合理性檢查不該因為型別而中斷。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sanity_check(t4: dict[str, Any], computed_price: int | None) -> list[dict[str, Any]]:
    """回傳可疑數值清單。空清單代表沒有明顯不合理的地方。"""
    out: list[dict[str, Any]] = []

    def flag(level: str, path: str, label: str, value: Any, reason: str) -> None:
        out.append(
            {
                "level": level,           # "error"：幾乎確定是誤讀｜"warn"：可疑
                "path": path,
                "label": label,
                "value": value,
                "reason": reason,
            }
        )

    for c in t4.get("comparables") or []:
        idx = c.get("index")
        p = f"comparables[{idx}]"

        unit_price = _num(c.get("normal_unit_price"))
        if unit_price is not None and unit_price <= 0:
            flag(
                "error", f"{p}.normal_unit_price", "土地正常單價", c.get("normal_unit_price"),
                "單價必須為正數。負數或 0 幾乎確定是辨識誤讀（例如吃到負號、"
                "或把空格當成 0），若照此計算會算出負的或零的補償金。",
            )

        for key, name in (
            ("individual_total_pct", "個別因素合計"),
            ("regional_adjustment_pct", "區域因素調整百分率"),
            ("date_adjustment_pct", "調整百分率（日期）"),
        ):
            v = _num(c.get(key))
            if v is not None and abs(v) > _PCT_ABS_LIMIT:
                flag(
                    "error", f"{p}.{key}", name, c.get(key),
                    f"修正率絕對值 {abs(v)}% 超過 {_PCT_ABS_LIMIT}%，"
                    f"幾乎確定是誤讀（例如小數點位置錯誤）。",
                )

        for fid, pct in (c.get("filed_corrections") or {}).items():
            v = _num(pct)
            if v is not None and abs(v) > _PCT_ABS_LIMIT:
                flag(
                    "error", f"{p}.filed_corrections.{fid}", fid, pct,
                    f"單一細項修正率絕對值 {abs(v)}% 超過 {_PCT_ABS_LIMIT}%。",
                )

        w = _num(c.get("weight_pct"))
        if w is not None and not 0 <= w <= 100:
            flag(
                "error", f"{p}.weight_pct", "權重", c.get("weight_pct"),
                "權重必須落在 0–100% 之間。",
            )

        for fid, name in _MUST_BE_POSITIVE.items():
            v = _num((c.get("facts") or {}).get(fid))
            if v is not None and v <= 0:
                flag(
                    "warn", f"{p}.facts.{fid}", name, (c.get("facts") or {}).get(fid),
                    f"{name}為 {v}，不應為 0 或負數。請確認表4 該格是否誤讀。",
                )

    bfacts = (t4.get("benchmark") or {}).get("facts") or {}
    for fid, name in _MUST_BE_POSITIVE.items():
        v = _num(bfacts.get(fid))
        if v is not None and v <= 0:
            flag(
                "warn", f"benchmark.facts.{fid}", name, bfacts.get(fid),
                f"比準地{name}為 {v}，不應為 0 或負數。",
            )

    if computed_price is not None and computed_price <= 0:
        flag(
            "error", "benchmark_comparison_price", "比準地比較價格", computed_price,
            "重算出的比準地比較價格不是正數。補償金不可能為零或負數，"
            "請先排除輸入值的誤讀再看審查結果。",
        )

    return out


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
        try:
            findings, price_impact, checked["table5_2_to_table4"] = _check_table4(
                t4, t52, rs_individual
            )
            layers["table5_2_to_table4"] = findings
        except ValueError as e:
            # 引擎算不下去（例如權重合計離譜、單價無法解析）時，不要讓整個
            # 審查變成一個錯誤訊息。第一、二層的結果仍然有效，而合理性檢查
            # 正好能指出是哪個值造成的——這比只回一句 ValueError 有用得多。
            not_checkable.append(
                {
                    "layer": "table5_2_to_table4",
                    "reason": "表4 無法重算：%s" % e,
                }
            )

    else:
        not_checkable.append({"layer": "table5_2_to_table4", "reason": "缺表4"})

    # 合理性檢查與三層檢核分開回報：前者是「這個數字本身有問題」，
    # 後者是「估價師填錯了」。混在一起會讓審查員分不出該去查書表還是查辨識。
    # 刻意放在 try/except 之後但不依賴它成功：引擎失敗時這裡照樣要跑。
    sanity = (
        _sanity_check(t4, price_impact["computed"] if price_impact else None)
        if t4
        else []
    )

    total = sum(len(v) for v in layers.values())
    return {
        "verdict": "mismatch" if total else "match",
        "finding_count": total,
        "checked": checked,
        "checked_total": sum(checked.values()),
        "layers": layers,
        "not_checkable": not_checkable,
        "sanity": sanity,
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
