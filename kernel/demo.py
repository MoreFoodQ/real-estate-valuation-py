"""Golden Case 一鍵重現，並列出每個數字的依據。

    python demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.compute import appraise_table4  # noqa: E402
from src.ruleset import load_ruleset  # noqa: E402
from src.validate import check_ruleset, errors, warnings  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    case = json.loads(
        (HERE / "golden" / "case_1140901_99_001.json").read_text(encoding="utf-8")
    )
    rs = load_ruleset("jinshan_commercial_individual")
    exp = case["expected"]

    print("=" * 78)
    print(f"案號 {case['case_id']}　估價基準日 {case['meta']['appraisal_base_date']}")
    print(f"規則 {rs.ruleset_id}（{rs.scope['district']} {rs.scope['land_use']}）")
    print(f"來源 {rs.source['doc']} 第 {rs.source['pages']} 頁，共 {len(rs)} 個細項")
    print("=" * 78)

    # 1. 規則自檢
    findings = check_ruleset(rs)
    print(f"\n【規則自檢】ERROR {len(errors(findings))} 件、WARN {len(warnings(findings))} 件")
    for f in findings:
        print(f"  {f}")

    # 2. 逐項計算
    result = appraise_table4(rs, case)
    r = result.comparables[0]
    c = case["comparables"][0]

    print(f"\n【表4 個別因素調整】比較標的{r.index}：{c['parcel']}")
    print(f"{'':2}{'細項':<12}{'比準地':<16}{'比較標的':<16}{'差異率':>8}")
    print("-" * 78)
    for row in r.rows:
        mark = "*" if row.correction.pct != 0 else " "
        b = f"{row.benchmark_value}({row.benchmark_grade.label})"
        cv = f"{row.comparable_value}({row.comparable_grade.label})"
        print(f"{mark} {row.label:<12}{b:<16}{cv:<16}{str(row.correction.pct) + '%':>8}")
    print("-" * 78)
    print(f"{'':2}{'合計':<12}{'':<32}{str(r.individual_total_pct) + '%':>8}")

    # 3. 非零項的完整依據
    print("\n【非零修正的依據鏈】")
    for row in r.rows:
        if row.correction.pct == 0:
            continue
        ev = row.as_evidence()
        print(f"\n  ● {ev['細項']}　{ev['差異率']}　(來源頁 {ev['來源頁']})")
        for line in ev["依據"]:
            print(f"      - {line}")

    # 4. 價格鏈
    print("\n【價格計算】")
    print(f"  土地正常單價                      {c['normal_unit_price']:>12,}")
    print(f"  × (1 + 交易日期調整 {r.date_pct}%)")
    print(f"  × (1 + 區域因素調整 {r.regional_pct}%)        ← 表5-2 總修正數")
    print(f"  × (1 + 個別因素合計 {r.individual_total_pct}%)")
    print(f"  = 未取整原值                      {r.trial_price_raw:>12}")
    print(f"  → 試算價格（四捨五入至個位）      {r.trial_price:>12,}")
    print(f"  × 權重 {r.weight_pct}%（相近程度：{r.similarity}）")
    print(f"  → 比準地比較價格                  {result.benchmark_comparison_price:>12,}")
    print(f"  → 比準地地價（第21條千位進位）    {result.benchmark_land_price:>12,}")

    # 5. 對答案
    checks = [
        ("個別因素合計", r.individual_total_pct, exp["individual_total_pct"]),
        ("絕對值加總", r.abs_sum_pct, exp["abs_sum_pct"]),
        ("試算價格", r.trial_price, exp["trial_price"]),
        ("比準地比較價格", result.benchmark_comparison_price, exp["benchmark_comparison_price"]),
        ("比準地地價", result.benchmark_land_price, exp["benchmark_land_price_rounded"]),
    ]
    print("\n【與官方答案比對】")
    ok = True
    for name, got, want in checks:
        hit = str(got) == str(want) or float(got) == float(want)
        ok &= hit
        print(f"  {'✓' if hit else '✗'} {name:<16} 本系統 {got!s:>12}　官方 {want!s:>12}")

    print("\n" + "=" * 78)
    print("全部相符：官方 Golden Case 完整重現" if ok else "有落差，需檢查")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
