"""矩陣查表單元測試。

這五個是 Golden Case 唯一的非零修正，也是唯一能測到
「級距邊界 × 矩陣方向 × 正負號」三件事同時正確的地方。
"""

from decimal import Decimal

import pytest

from src.classify import classify
from src.matrix import lookup, matrix_cells
from src.ruleset import load_ruleset

IND = load_ruleset("jinshan_commercial_individual")


def _correct(factor_id, benchmark_value, comparable_value) -> Decimal:
    f = IND[factor_id]
    bg = classify(f, benchmark_value)
    cg = classify(f, comparable_value)
    return lookup(f, bg.grade, cg.grade).pct


@pytest.mark.parametrize(
    "factor_id,bench,comp,expected,why",
    [
        ("individual.parcel.depth", 23, 16, "1.0", "普通 vs 稍劣"),
        ("individual.road.road_type", "主要道路", "次要道路", "2.0", "優 vs 稍優"),
        ("individual.road.frontage_road_width", 18, 6, "5.0", "稍優 vs 稍劣"),
        ("individual.surroundings.nuisance", 260, 80, "3.0", "普通 vs 劣"),
        ("individual.surroundings.parking", "可路邊停車", "不可路邊停車", "2.0", "優 vs 劣"),
    ],
)
def test_golden_nonzero_corrections(factor_id, bench, comp, expected, why):
    assert _correct(factor_id, bench, comp) == Decimal(expected), why


def test_direction_matters_swapping_flips_sign():
    """比準地與比較標的互換，符號必須翻轉。防 matrix[a][b] 寫反。"""
    fwd = _correct("individual.road.frontage_road_width", 18, 6)
    rev = _correct("individual.road.frontage_road_width", 6, 18)
    assert fwd == Decimal("5.0")
    assert rev == Decimal("-5.0")


def test_same_grade_is_zero():
    assert _correct("individual.parcel.area", 113.21, 111.85) == 0, "同為優 → 0"
    assert _correct("individual.admin.building_coverage", 70, 70) == 0


def test_max_range_equals_you_vs_lie():
    """黃底最大值必須等於矩陣[優][劣]。這是 PDF 上獨立印出的數字，可交叉驗證 step。"""
    for f in IND.factors.values():
        cells = matrix_cells(f)
        assert cells[0][f.grade_count - 1] == f.max_range, f.factor_id


def test_out_of_range_grade_raises():
    with pytest.raises(ValueError, match="超出 1..5"):
        lookup(IND["individual.parcel.area"], 1, 6)
