"""表5-2 辨識器測試。

表5-2 在 Golden Case 裡全部是 0.00%（比準地與比較標的同區段），
所以**測不到矩陣查表**——一個壞掉的矩陣引擎也會碰巧全對。
這裡能驗的是：28 個細項的等級抽取、8 個群組的歸屬、小計與總修正數的落點。
矩陣方向與正負號由表4 的 5 個非零修正去釘（見 test_table4.py）。

最有價值的一條是 `test_grades_match_table1`：表5-2 的等級必須與表1 一致，
這正是作業手冊審查重點第 vi 項，而且一條測試同時驗證兩支辨識器。
"""

from __future__ import annotations

import json

import pytest

import paths
from parser.detect import find_page
from parser.extract import load_pages
from parser.table5_2 import FACTOR_ROWS, parse


@pytest.fixture(scope="module")
def pages():
    return load_pages(paths.require(paths.SAMPLE_FORMS_PDF))


@pytest.fixture(scope="module")
def parsed(pages):
    return parse(find_page(pages, "表5-2"))


@pytest.fixture(scope="module")
def golden():
    with open(
        paths.ROOT / "parser" / "golden" / "table5_2_1140901_99_001.json",
        encoding="utf-8",
    ) as f:
        return json.load(f)


# ---------- 表頭 ----------


def test_case_id_and_land_use(parsed, golden):
    assert parsed.case_id == golden["case_id"]
    assert parsed.land_use == golden["land_use"]


def test_segments(parsed, golden):
    """比準地與比較標的同區段，這是表5-2 全為 0.00% 的原因。"""
    assert parsed.benchmark_segment == golden["benchmark_segment"]
    assert [c["segment"] for c in parsed.comparables] == golden["comparable_segments"]
    assert [c["example_no"] for c in parsed.comparables] == golden["example_nos"]


def test_only_one_comparable_is_filled(parsed):
    assert len(parsed.comparables) == 1


# ---------- 28 個細項 ----------


def test_factor_mapping_covers_twenty_eight(parsed):
    """28 個細項一個都不能少：少一個，該類小計與總修正數就會錯。"""
    assert len(FACTOR_ROWS) == 28
    assert len({fid for _, fid in FACTOR_ROWS}) == 28
    assert set(parsed.benchmark_grades) == {fid for _, fid in FACTOR_ROWS}


def test_benchmark_grades_match_golden(parsed, golden):
    got = {
        fid: [cell["grade"], cell["label"]]
        for fid, cell in parsed.benchmark_grades.items()
    }
    assert got == golden["grades"]


def test_comparable_grades_equal_benchmark(parsed, golden):
    """同區段，所以比較標的 28 項等級必須與比準地完全相同。"""
    got = {
        fid: [cell["grade"], cell["label"]]
        for fid, cell in parsed.comparables[0]["grades"].items()
    }
    assert got == golden["grades"]


def test_no_grade_warnings(parsed):
    """等級欄的數字與文字必須自相一致（1↔優、5↔劣、二級制 1↔無）。

    官方範本不該有任何不一致；有的話是辨識器的檢核邏輯抓錯了，不是資料錯。
    """
    assert parsed.warnings == []


# ---------- 群組與加總 ----------


def test_groups_are_exactly_eight(parsed, golden):
    """8 個主要項目。範本裡「其他影響／因素(8)」被切成兩個網格列、
    總修正數列的第一欄也是文字，照收會多出假群組——這條防的是那個。
    """
    assert [g["label"] for g in parsed.groups] == golden["groups"]


def test_group_membership_matches_golden(parsed, golden):
    got = {g["label"]: g["factor_ids"] for g in parsed.groups}
    assert got == golden["group_membership"]


def test_other_factors_group_has_no_detail_rows(parsed):
    """其他影響因素(8) 是自由欄位，無級距、無細項（手冊 p.33）。"""
    other = next(g for g in parsed.groups if g["label"].endswith("(8)"))
    assert other["factor_ids"] == []


def test_filed_subtotals_and_total(parsed, golden):
    """小計與總修正數印在合併儲存格裡，落點與資料列的修正百分比欄不同。"""
    c = parsed.comparables[0]
    assert c["filed_subtotals"] == golden["filed_subtotals"]
    assert c["filed_total"] == golden["filed_total"]


def test_filed_corrections_all_zero(parsed):
    c = parsed.comparables[0]
    assert len(c["filed_corrections"]) == 28
    assert set(c["filed_corrections"].values()) == {0}


# ---------- 跨表一致性（手冊審查重點第 vi 項） ----------


def test_grades_match_table1(pages, golden):
    """表5-2 的等級必須與表1 勘查表所載一致。

    表1 每個細項左欄印的是「等級 級數」兩個數字（例如「3 5 主要道路」
    ＝第3級／共5級），這裡只比等級。級數不一定是 5——都市計畫內外、
    有無禁止建築都是 2 級——所以不能用級數當常數。

    這條同時驗證兩支辨識器：任何一邊抽錯就會紅。
    """
    from parser.table1 import parse as parse_table1

    t1 = parse_table1(find_page(pages, "表1"))
    for factor_id, (grade, _label) in golden["grades"].items():
        assert t1.grades[factor_id]["grade"] == grade, factor_id
