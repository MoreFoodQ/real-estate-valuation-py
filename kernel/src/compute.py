"""加總與價格計算。

三條硬規則（皆有官方出處）：
1. 小計／合計是「各項直接相加」，不是連乘。
   佐證：作業手冊 p.96 表5-1 範例 0+(-36.16)+12.50+(-5.00)+2.25+13.75+10.00+(-2.50) = -5.16
2. 全程保留精度，只在最終取整。
   佐證：184763×1.02×1.13 = 212957.83 → 212,958（官方值）；
   若先用表上顯示的 188,459 續算會得 212,959，與官方不符。
3. 尾數規則分兩種：
   - 表4 比準地比較價格：四捨五入至個位數（作業手冊 p.53）
   - 表14 比準地地價／表6 宗地市價：分段無條件進位（查估辦法第21條）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from .classify import Grade, classify
from .matrix import Correction, lookup
from .ruleset import RuleSet, dec

ONE = Decimal(1)
HUNDRED = Decimal(100)


# ---------- 加總 ----------

def total_pct(corrections: list[Correction]) -> Decimal:
    """個別因素合計／區域因素總修正數：各項直接相加。"""
    return sum((c.pct for c in corrections), Decimal(0))


def abs_sum_pct(
    corrections: list[Correction],
    date_pct: Decimal | float = 0,
    regional_pct: Decimal | float = 0,
) -> Decimal:
    """調整百分率絕對值加總（作業手冊 p.53：各項調整百分率先取絕對值後加總）。

    Golden Case: |2.00| + |0.00| + |1|+|2|+|5|+|3|+|2| = 15.00
    """
    return (
        abs(dec(date_pct))
        + abs(dec(regional_pct))
        + sum((abs(c.pct) for c in corrections), Decimal(0))
    )


def similarity_and_weights(abs_sums: list[Decimal]) -> list[tuple[str, Decimal]]:
    """依「調整百分率絕對值加總」決定相近程度與權重。

    作業手冊 p.53 範例：3件 7%/10%/15% → 較高/普通/較低 → 50%/30%/20%
                       2件 7%/10%     → 較高/普通      → 70%/30%
                       1件            → 普通           → 100%
    加總愈多者權重愈少；惟手冊亦要求配合蒐集資料可信度綜合決定，故此為預設建議值。
    """
    n = len(abs_sums)
    presets = {
        1: [("普通", Decimal(100))],
        2: [("較高", Decimal(70)), ("普通", Decimal(30))],
        3: [("較高", Decimal(50)), ("普通", Decimal(30)), ("較低", Decimal(20))],
    }
    if n not in presets:
        raise ValueError(f"比較標的件數 {n} 超出辦法第19條規定之 1~3 件")

    order = sorted(range(n), key=lambda i: abs_sums[i])  # 加總小 → 相近程度高
    out: list[tuple[str, Decimal]] = [("", Decimal(0))] * n
    for rank, idx in enumerate(order):
        out[idx] = presets[n][rank]
    return out


# ---------- 尾數 ----------

def round_half_up(value: Decimal | float) -> int:
    """四捨五入至個位數（作業手冊 p.53，比準地比較價格）。"""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_up_by_tier(value: Decimal | float) -> int:
    """查估辦法第21條分段無條件進位（比準地地價、宗地市價）。

    100元以下→個位；逾100至1000→十位；逾1000至10萬→百位；逾10萬→千位。
    """
    v = dec(value)
    if v <= 100:
        unit = Decimal(1)
    elif v <= 1000:
        unit = Decimal(10)
    elif v <= 100_000:
        unit = Decimal(100)
    else:
        unit = Decimal(1000)
    return int((v / unit).to_integral_value(rounding=ROUND_CEILING) * unit)


# ---------- 價格 ----------

def trial_price(
    normal_unit_price: Decimal | float,
    date_pct: Decimal | float,
    regional_pct: Decimal | float,
    individual_pct: Decimal | float,
) -> tuple[int, Decimal]:
    """試算價格。回傳 (顯示用整數, 未取整原值)。

    原值必須傳給下游，不可用取整後的值續算。
    """
    raw = (
        dec(normal_unit_price, field="表4 土地正常單價")
        * (ONE + dec(date_pct, field="表4 調整百分率（日期）") / HUNDRED)
        * (ONE + dec(regional_pct, field="表4 區域因素調整百分率") / HUNDRED)
        * (ONE + dec(individual_pct, field="表4 個別因素合計") / HUNDRED)
    )
    return round_half_up(raw), raw


# 權重合計的容差。書表上的權重是整數百分比，3 件比較標的各填 33% 就只有
# 99%——這是估價師的正常填法，不是錯誤。容差內按比例正規化後續算，並發警告；
# 超出容差才視為填載錯誤。
WEIGHT_TOLERANCE = Decimal(1)


def benchmark_comparison_price(
    trials: list[int],
    weights_pct: list[Decimal],
    *,
    warnings: list[str] | None = None,
) -> int:
    """比準地比較價格 = Σ(試算價格 × 權重)，四捨五入至個位數。

    權重合計不是 100% 時：容差（±1%）內按比例正規化並記錄警告，
    超出容差才 raise。`warnings` 傳進來就會把訊息 append 上去。
    """
    if len(trials) != len(weights_pct):
        raise ValueError("試算價格與權重數量不符")
    if not weights_pct:
        raise ValueError("沒有比較標的，無法計算比準地比較價格")

    tw = sum(weights_pct, Decimal(0))
    if tw <= 0:
        raise ValueError(f"權重合計必須為正數，實得 {tw}%")

    if tw != HUNDRED:
        if abs(tw - HUNDRED) > WEIGHT_TOLERANCE:
            raise ValueError(
                f"權重合計必須為 100%（容差 ±{WEIGHT_TOLERANCE}%），實得 {tw}%。"
                f"請確認表4 的權重欄是否誤讀或填錯。"
            )
        # 容差內：按比例正規化。不直接沿用原權重，否則加總 99% 會讓價格偏低 1%。
        msg = (
            f"表4 權重合計為 {tw}%，不是 100%（在 ±{WEIGHT_TOLERANCE}% 容差內）。"
            f"已按比例正規化後計算，建議人工確認權重欄。"
        )
        if warnings is not None:
            warnings.append(msg)
        weights_pct = [w * HUNDRED / tw for w in weights_pct]

    acc = sum((dec(t) * w / HUNDRED for t, w in zip(trials, weights_pct)), Decimal(0))
    return round_half_up(acc)


# ---------- 全鏈路 ----------

@dataclass
class FactorRow:
    factor_id: str
    label: str
    table4_row: int | None
    benchmark_value: Any
    comparable_value: Any
    benchmark_grade: Grade
    comparable_grade: Grade
    correction: Correction

    def as_evidence(self) -> dict:
        return {
            "細項": self.label,
            "比準地": f"{self.benchmark_value}（{self.benchmark_grade.label}）",
            "比較標的": f"{self.comparable_value}（{self.comparable_grade.label}）",
            "差異率": f"{self.correction.pct}%",
            "依據": [
                self.benchmark_grade.reason,
                self.comparable_grade.reason,
                self.correction.reason,
            ],
            "來源頁": self.correction.source_page,
        }


@dataclass
class ComparableResult:
    index: int
    rows: list[FactorRow]
    date_pct: Decimal
    regional_pct: Decimal
    individual_total_pct: Decimal
    abs_sum_pct: Decimal
    trial_price: int
    trial_price_raw: Decimal = field(repr=False)
    similarity: str = ""
    weight_pct: Decimal = Decimal(0)

    @property
    def nonzero(self) -> dict[str, Decimal]:
        return {r.factor_id: r.correction.pct for r in self.rows if r.correction.pct != 0}


def appraise_comparable(
    rs: RuleSet,
    benchmark_facts: dict[str, Any],
    comparable: dict[str, Any],
    *,
    only: list[str] | None = None,
) -> ComparableResult:
    """對單一比較標的跑完個別因素調整與試算價格。"""
    ids = only if only is not None else rs.factor_ids
    cfacts = comparable["facts"]

    rows: list[FactorRow] = []
    for fid in ids:
        if fid not in benchmark_facts or fid not in cfacts:
            continue  # 免修正項目（表4 以「-」表示），與差異率為 0 者區分
        f = rs[fid]
        bg = classify(f, benchmark_facts[fid])
        cg = classify(f, cfacts[fid])
        rows.append(
            FactorRow(
                factor_id=fid,
                label=f.label,
                table4_row=f.table4_row,
                benchmark_value=benchmark_facts[fid],
                comparable_value=cfacts[fid],
                benchmark_grade=bg,
                comparable_grade=cg,
                correction=lookup(f, bg.grade, cg.grade),
            )
        )

    corrections = [r.correction for r in rows]
    date_pct = dec(comparable.get("date_adjustment_pct", 0))
    regional_pct = dec(comparable.get("regional_adjustment_pct", 0))
    ind_total = total_pct(corrections)
    price, raw = trial_price(
        comparable["normal_unit_price"], date_pct, regional_pct, ind_total
    )

    return ComparableResult(
        index=comparable.get("index", 1),
        rows=rows,
        date_pct=date_pct,
        regional_pct=regional_pct,
        individual_total_pct=ind_total,
        abs_sum_pct=abs_sum_pct(corrections, date_pct, regional_pct),
        trial_price=price,
        trial_price_raw=raw,
    )


@dataclass
class Table4Result:
    comparables: list[ComparableResult]
    benchmark_comparison_price: int
    benchmark_land_price: int
    # 「算得出來但需要人工確認」的事項。與 raise 的差別：這些不阻擋計算，
    # 但必須讓審查員看到，不能靜默吞掉。
    warnings: list[str] = field(default_factory=list)


def appraise_table4(
    rs: RuleSet,
    case: dict[str, Any],
    *,
    weights_pct: list[Decimal] | None = None,
) -> Table4Result:
    """表4 全鏈路 → 比準地比較價格 → 表14 比準地地價（尾數進位）。"""
    bfacts = case["benchmark"]["facts"]
    results = [appraise_comparable(rs, bfacts, c) for c in case["comparables"]]

    if weights_pct is None:
        given = [c.get("weight_pct") for c in case["comparables"]]
        if all(g is not None for g in given):
            weights_pct = [dec(g) for g in given]
            for r, w in zip(results, weights_pct):
                r.weight_pct = w
                r.similarity = similarity_and_weights([x.abs_sum_pct for x in results])[
                    results.index(r)
                ][0]
        else:
            sw = similarity_and_weights([r.abs_sum_pct for r in results])
            weights_pct = [w for _, w in sw]
            for r, (lab, w) in zip(results, sw):
                r.similarity, r.weight_pct = lab, w
    else:
        for r, w in zip(results, weights_pct):
            r.weight_pct = w

    warnings: list[str] = []
    bcp = benchmark_comparison_price(
        [r.trial_price for r in results], weights_pct, warnings=warnings
    )
    return Table4Result(results, bcp, round_up_by_tier(bcp), warnings)
