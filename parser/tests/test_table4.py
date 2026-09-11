"""表4 辨識器測試。

靶不是「看起來對」，是 `kernel/golden/case_1140901_99_001.json`——
那份 JSON 是人工從官方範本抄出來的，已經被 kernel 的 59 個測試用來
重現官方答案（13.00% / 212,958 / 213,000）。所以辨識器只要能產出
同一份 facts，就等於「辨識 → 計算」整條鏈都被官方答案釘住了。
"""

from __future__ import annotations

import json

import pytest

import paths
from parser.detect import detect_table, find_page
from parser.extract import load_pages
from parser.table4 import FACTOR_ROWS, parse


@pytest.fixture(scope="module")
def pages():
    return load_pages(paths.require(paths.SAMPLE_FORMS_PDF))


@pytest.fixture(scope="module")
def parsed(pages):
    return parse(find_page(pages, "表4"))


@pytest.fixture(scope="module")
def golden():
    with open(paths.require(paths.GOLDEN_CASE), encoding="utf-8") as f:
        return json.load(f)


# ---------- 表別判斷 ----------


def test_detect_only_three_form_pages(pages):
    """範本 6 頁裡有 3 頁是區段圖，不能被誤判成書表。"""
    codes = [detect_table(p) for p in pages]
    assert codes == ["表1", "表5-2", "表4", None, None, None]


# ---------- 案件識別 ----------


def test_case_id_and_base_date(parsed, golden):
    assert parsed.case_id == golden["case_id"]
    assert parsed.appraisal_base_date == golden["meta"]["appraisal_base_date"]


def test_parcels_and_segments(parsed, golden):
    assert parsed.benchmark["parcel"] == golden["benchmark"]["parcel"]
    assert parsed.benchmark["segment"] == golden["benchmark"]["segment"]
    c, gc = parsed.comparables[0], golden["comparables"][0]
    assert c["parcel"] == gc["parcel"]
    assert c["segment"] == gc["segment"]
    assert c["example_no"] == gc["example_no"]


def test_only_one_comparable_is_filled(parsed):
    """版面固定留 3 件比較標的，範本只填 1 件，空欄不能被當成資料。"""
    assert len(parsed.comparables) == 1


# ---------- 核心驗收：facts 與 golden 逐項相符 ----------


def test_benchmark_facts_match_golden(parsed, golden):
    assert parsed.benchmark["facts"] == golden["benchmark"]["facts"]


def test_comparable_facts_match_golden(parsed, golden):
    assert parsed.comparables[0]["facts"] == golden["comparables"][0]["facts"]


def test_all_nineteen_factors_are_covered(parsed):
    """19 個個別因素一個都不能少——少一個 kernel 的合計就會算錯。"""
    assert len(FACTOR_ROWS) == 19
    assert set(parsed.benchmark["facts"]) == {fid for _, fid, _ in FACTOR_ROWS}
    assert all(v is not None for v in parsed.benchmark["facts"].values())


# ---------- 價格欄 ----------


def test_price_fields_match_golden(parsed, golden):
    c, gc = parsed.comparables[0], golden["comparables"][0]
    assert c["transaction_date"] == gc["transaction_date"]
    assert c["normal_unit_price"] == gc["normal_unit_price"]
    assert c["date_adjustment_pct"] == gc["date_adjustment_pct"]
    assert c["regional_adjustment_pct"] == gc["regional_adjustment_pct"]
    assert c["weight_pct"] == gc["weight_pct"]
    assert (
        c["date_adjusted_unit_price_displayed"]
        == gc["date_adjusted_unit_price_displayed"]
    )


def test_summary_fields_match_golden(parsed, golden):
    c, exp = parsed.comparables[0], golden["expected"]
    assert c["individual_total_pct"] == exp["individual_total_pct"]
    assert c["abs_sum_pct"] == exp["abs_sum_pct"]
    assert c["similarity_label"] == exp["similarity_label"]
    assert c["trial_price"] == exp["trial_price"]


# ---------- 估價師填的修正率（審查模式的輸入） ----------


def test_filed_corrections_match_golden_nonzero(parsed, golden):
    """表4 上估價師填的差異率，非零項必須恰好是官方那 5 項。

    這是審查模式的原料：把這些「人填的值」跟 kernel 重算的值逐格比，
    才能指出哪一格錯了、賠償金差多少。
    """
    filed = parsed.comparables[0]["filed_corrections"]
    nonzero = {k: v for k, v in filed.items() if v != 0}
    assert nonzero == golden["expected"]["nonzero_corrections"]


# ---------- 顯示標籤 ----------


def test_fact_labels_cover_golden(parsed, golden):
    """golden 的 fact_labels 只記了人工當時在意的幾項（比較標的只記 2 項），
    所以是子集比對，不是相等比對。辨識器會抽出全部 7 項，那是進步不是錯。
    """
    for side, gside in (
        (parsed.benchmark, golden["benchmark"]),
        (parsed.comparables[0], golden["comparables"][0]),
    ):
        for factor_id, label in gside["fact_labels"].items():
            assert side["fact_labels"][factor_id] == label


# ---------- 座標定位的必要性 ----------


def test_label_row_can_be_offset_from_its_values(pages):
    """「9深度(M)」的標籤與它的值不在同一個 y——這正是不能靠文字順序、
    也不能全域 y 分群的原因。這個測試把版面的這個事實記錄下來，
    以免有人日後把 y 容差調小而讓深度整欄變空。
    """
    page = find_page(pages, "表4")
    label = next(w for w in page.words if w.text == "9深度(M)")
    depth_value = next(w for w in page.words if w.text == "23")
    offset = abs(label.y_center - depth_value.y_center)
    assert 0 < offset < 5.0


# ---------- provenance ----------


def test_every_fact_has_provenance(parsed):
    """每個值都要能指回 PDF 的頁與位置，這是「沒讓 AI 生成數字」的證據。"""
    entries = parsed.provenance.to_dict()
    for factor_id in parsed.benchmark["facts"]:
        src = entries["benchmark.facts.%s" % factor_id]
        assert src["page"] == 3
        assert src["bbox"] is not None
        assert src["raw_text"]
        assert src["backend"] == "text_layer"
