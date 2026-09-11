"""修正矩陣查表：(比準地等級, 比較標的等級) -> 修正百分比。

方向寫在參數名稱上，不用 matrix[a][b]。
依據：評價基準明細表版面 —「宗地(比準地)」為列、「比準地(比較標的)」為欄。
Golden Case 反證：道路種類 比準地=主要道路(優) / 比較標的=次要道路(稍優) → +2.00%。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .ruleset import Factor, dec


@dataclass(frozen=True)
class Correction:
    factor_id: str
    benchmark_grade: int
    comparable_grade: int
    pct: Decimal
    reason: str
    source_page: int | None = None


def matrix_cells(factor: Factor) -> list[list[Decimal]]:
    """展開成完整 N×N，供 validator 檢查與 UI 顯示。"""
    m = factor.matrix
    n = factor.grade_count
    kind = m.get("kind")

    if kind == "linear_step":
        step = dec(m["step"])
        return [[(dec(j) - dec(i)) * step for j in range(1, n + 1)] for i in range(1, n + 1)]
    if kind == "cells":
        cells = [[dec(x) for x in row] for row in m["cells"]]
        if len(cells) != n or any(len(r) != n for r in cells):
            raise ValueError(f"{factor.factor_id}: cells 維度與 grade_count={n} 不符")
        return cells
    raise ValueError(f"{factor.factor_id}: 未支援的 matrix kind {kind!r}")


def lookup(factor: Factor, benchmark_grade: int, comparable_grade: int) -> Correction:
    n = factor.grade_count
    for name, g in (("比準地", benchmark_grade), ("比較標的", comparable_grade)):
        if not 1 <= g <= n:
            raise ValueError(f"{factor.factor_id}: {name}等級 {g} 超出 1..{n}")

    cells = matrix_cells(factor)
    pct = cells[benchmark_grade - 1][comparable_grade - 1]

    bl = factor.label_of(benchmark_grade)
    cl = factor.label_of(comparable_grade)
    return Correction(
        factor.factor_id, benchmark_grade, comparable_grade, pct,
        f"矩陣[比準地={benchmark_grade} {bl}][比較標的={comparable_grade} {cl}] = {pct}%",
        factor.source_page,
    )
