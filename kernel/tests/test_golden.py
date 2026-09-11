"""Golden Case 整合 / 端到端測試。

案號 1140901-99-001（查估書表範本，官方已填）。
表4 → 比準地比較價格 212,958 → 表14 比準地地價 213,000。
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.classify import classify
from src.compute import (
    appraise_table4,
    round_half_up,
    round_up_by_tier,
    similarity_and_weights,
    trial_price,
)
from src.ruleset import load_ruleset

CASE = json.loads(
    (Path(__file__).resolve().parent.parent / "golden" / "case_1140901_99_001.json")
    .read_text(encoding="utf-8")
)
IND = load_ruleset("jinshan_commercial_individual")
EXP = CASE["expected"]


@pytest.fixture(scope="module")
def result():
    return appraise_table4(IND, CASE)


# ---------- 整合：19 個細項的等級 ----------

def test_all_19_factors_are_encoded():
    assert len(IND) == 19, "表4 個別因素共 19 個細項"
    assert set(IND.factor_ids) == set(EXP["grades"]), "規則檔與 Golden 期望值的細項須一一對應"


def test_every_grade_matches_official_form():
    bfacts = CASE["benchmark"]["facts"]
    cfacts = CASE["comparables"][0]["facts"]
    for fid, (want_b, want_c) in EXP["grades"].items():
        f = IND[fid]
        assert classify(f, bfacts[fid]).grade == want_b, f"{fid} 比準地"
        assert classify(f, cfacts[fid]).grade == want_c, f"{fid} 比較標的"


# ---------- 整合：合計 ----------

def test_individual_total_is_13_percent(result):
    r = result.comparables[0]
    assert r.individual_total_pct == Decimal("13.0")


def test_nonzero_set_is_exactly_five(result):
    """不只總和要對，非零的「是哪五項」也要對。
    否則兩個錯誤互相抵銷也會湊出 13%。"""
    got = {k: v for k, v in result.comparables[0].nonzero.items()}
    want = {k: Decimal(str(v)) for k, v in EXP["nonzero_corrections"].items()}
    assert got == want


def test_abs_sum_is_15_percent(result):
    """|2.00| + |0.00| + |1|+|2|+|5|+|3|+|2| = 15.00"""
    assert result.comparables[0].abs_sum_pct == Decimal("15.0")


def test_regional_adjustment_is_zero(result):
    """比準地與比較標的同屬 P002-00，區域因素總修正數為 0。"""
    assert CASE["benchmark"]["segment"] == CASE["comparables"][0]["segment"]
    assert result.comparables[0].regional_pct == Decimal("0.0")


# ---------- 端到端：價格 ----------

def test_trial_price_is_212958(result):
    assert result.comparables[0].trial_price == 212958


def test_benchmark_comparison_price_is_212958(result):
    assert result.benchmark_comparison_price == 212958


def test_benchmark_land_price_rounds_up_to_213000(result):
    """查估辦法第21條：逾 10 萬元者計算至千位數，未達千位數無條件進位。"""
    assert result.benchmark_land_price == 213000


def test_single_comparable_gets_putong_and_100_percent(result):
    r = result.comparables[0]
    assert r.weight_pct == Decimal(100)
    assert similarity_and_weights([r.abs_sum_pct]) == [("普通", Decimal(100))]


# ---------- 最關鍵的陷阱：中間值不得取整 ----------

def test_must_not_round_intermediate_values():
    """表4 顯示的「調整至估價基準日單價 188,459」是顯示欄位。

    用它續算會得到 212,959，與官方 212,958 差 1 元。
    這個測試把陷阱鎖住：正確做法是全程用未取整原值連乘。
    """
    normal = Decimal("184763")
    displayed = Decimal(CASE["comparables"][0]["date_adjusted_unit_price_displayed"])
    assert displayed == 188459

    wrong = round_half_up(displayed * Decimal("1.13"))
    assert wrong == 212959, "用顯示值續算會錯 1 元"

    right, raw = trial_price(normal, Decimal("2.0"), Decimal("0.0"), Decimal("13.0"))
    assert right == 212958
    assert raw == Decimal("212957.833800")
    assert right != wrong


def test_intermediate_raw_value_is_not_the_displayed_one():
    raw = Decimal("184763") * (Decimal(1) + Decimal("2.0") / 100)
    assert raw == Decimal("188458.26")
    assert round_half_up(raw) == 188458
    assert raw != Decimal("188459"), "顯示值 188,459 與計算值 188,458.26 不同，不可混用"


# ---------- 尾數規則四段 ----------

@pytest.mark.parametrize(
    "value,expected,tier",
    [
        (99.1, 100, "100元以下 → 個位"),
        (100, 100, "100元以下邊界"),
        (100.1, 110, "逾100至1000 → 十位"),
        (1000, 1000, "逾100至1000邊界"),
        (1000.1, 1100, "逾1000至10萬 → 百位"),
        (100_000, 100_000, "逾1000至10萬邊界"),
        (100_000.1, 101_000, "逾10萬 → 千位"),
        (212_958, 213_000, "Golden Case"),
    ],
)
def test_round_up_by_tier(value, expected, tier):
    assert round_up_by_tier(value) == expected, tier
