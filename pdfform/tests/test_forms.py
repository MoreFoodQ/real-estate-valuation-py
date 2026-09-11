"""產表測試。

驗收方式是**往返**：官方範本 → 辨識 → 計算 → 產出三張書表 → 再用同一組
辨識器讀回來 → 值必須與官方答案相同。

這條比「檔案產出來了」強得多：它同時證明版面沒跑掉（不然辨識器找不到欄位）、
值填在對的格子裡（不然讀回來會對到別的欄位）、而且數字是官方答案
（13.00% / 212,958 / 213,000）。任何一環壞掉都會紅。
"""

from __future__ import annotations

import json

import pytest

import paths
from api.kernel_api import appraise_table4, classify, load_ruleset, lookup
from parser import table1, table4, table5_2
from parser.detect import detect_table, find_page
from parser.extract import load_pages
from pdfform.forms import build_forms


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("forms")
    return build_forms(
        paths.require(paths.SAMPLE_FORMS_PDF),
        out,
        regional=load_ruleset("jinshan_commercial_regional"),
        individual=load_ruleset("jinshan_commercial_individual"),
        appraise=appraise_table4,
        classify=classify,
        lookup=lookup,
    )


@pytest.fixture(scope="module")
def golden():
    with open(paths.require(paths.GOLDEN_CASE), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_regional():
    with open(
        paths.ROOT / "parser" / "golden" / "table5_2_1140901_99_001.json",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def test_three_files_are_produced(generated):
    assert set(generated) == {"表1", "表5-2", "表4"}
    for code, path in generated.items():
        assert path.exists(), code
        assert path.stat().st_size > 10_000, code  # 空白頁大約 1KB


def test_page_size_matches_the_official_form(generated):
    """表4 是橫式 A4、表1 與表5-2 是直式。版面尺寸跑掉就不是官方格式了。"""
    sizes = {}
    for code, path in generated.items():
        page = load_pages(path)[0]
        sizes[code] = (round(page.width), round(page.height))
    assert sizes["表1"] == (595, 842)
    assert sizes["表5-2"] == (595, 842)
    assert sizes["表4"] == (842, 595)


def test_generated_forms_are_still_recognisable(generated):
    """產出的檔案要能被自己的辨識器認出表別——標題與版面都還在。"""
    for code, path in generated.items():
        assert detect_table(load_pages(path)[0]) == code


# ---------- 往返：讀回來的值要與官方答案相同 ----------


def test_table4_roundtrip(generated, golden):
    page = find_page(load_pages(generated["表4"]), "表4")
    back = table4.parse(page)

    assert back.case_id == golden["case_id"]
    assert back.benchmark["facts"] == golden["benchmark"]["facts"]
    assert back.comparables[0]["facts"] == golden["comparables"][0]["facts"]

    c = back.comparables[0]
    assert c["normal_unit_price"] == golden["comparables"][0]["normal_unit_price"]
    assert c["individual_total_pct"] == golden["expected"]["individual_total_pct"]
    assert c["abs_sum_pct"] == golden["expected"]["abs_sum_pct"]
    assert c["similarity_label"] == golden["expected"]["similarity_label"]
    assert c["trial_price"] == golden["expected"]["trial_price"]
    assert back.benchmark_comparison_price == golden["expected"]["benchmark_comparison_price"]


def test_table4_corrections_roundtrip(generated, golden):
    """填進去的差異率是引擎算的；讀回來非零項必須恰好是官方那 5 項。"""
    back = table4.parse(find_page(load_pages(generated["表4"]), "表4"))
    filed = back.comparables[0]["filed_corrections"]
    nonzero = {k: v for k, v in filed.items() if v != 0}
    assert nonzero == golden["expected"]["nonzero_corrections"]


def test_table5_2_roundtrip(generated, golden_regional):
    """28 個細項的等級是引擎從表1 的量測值算出來的，讀回來要與官方所填相同。"""
    back = table5_2.parse(find_page(load_pages(generated["表5-2"]), "表5-2"))
    got = {
        fid: [cell["grade"], cell["label"]]
        for fid, cell in back.benchmark_grades.items()
    }
    assert got == golden_regional["grades"]
    assert back.comparables[0]["filed_total"] == 0
    assert back.comparables[0]["filed_subtotals"] == golden_regional["filed_subtotals"]
    assert back.warnings == []


def test_table1_roundtrip(generated, golden_regional):
    """表1 的等級是引擎算的、量測值是照抄的，兩者讀回來都要對。"""
    back = table1.parse(find_page(load_pages(generated["表1"]), "表1"))
    got = {fid: cell["grade"] for fid, cell in back.grades.items()}
    expected = {fid: g for fid, (g, _label) in golden_regional["grades"].items()}
    assert got == expected
    assert back.surveys["regional.transport.main_road_width"]["numeric"] == 18
    assert back.warnings == []


def test_two_level_factors_keep_the_form_wording(generated):
    """二級制的「有無禁止建築／有無限制建築」在書表上印的是「無／有」，不是「優／劣」。

    同為二級的「都市計畫（內、外）」印的卻是「優／劣」，所以這不是級數的問題，
    是逐細項的用字，規則集用 grade_labels 覆寫。填錯會讓表5-2 與勘查表對不上
    （審查重點第 vi 項要求兩表一致）。
    """
    back = table5_2.parse(find_page(load_pages(generated["表5-2"]), "表5-2"))
    assert back.benchmark_grades["regional.land_control.build_prohibition"]["label"] == "無"
    assert back.benchmark_grades["regional.land_control.build_restriction"]["label"] == "無"
    assert back.benchmark_grades["regional.land_control.urban_plan"]["label"] == "優"


# ---------- 誠實性 ----------


def test_unfilled_slots_are_left_blank_not_copied(generated):
    """沒有給值的格子必須留白，不能默默沿用原檔的內容。

    若沒給值就回填原檔，產出的表會看起來很完整，但沒人分得出哪些格子是
    系統算的、哪些是原檔留下的——那就失去「每個數字都能指回來源」的意義。
    """
    from pdfform import template

    page = find_page(load_pages(paths.SAMPLE_FORMS_PDF), "表4")
    boxes = {
        path: tuple(src.bbox)
        for path, src in table4.parse(page).provenance.entries.items()
        if src.bbox is not None
    }
    tpl = template.build(paths.SAMPLE_FORMS_PDF, page.number, "表4", boxes)

    out = generated["表4"].parent / "blank.pdf"
    from pdfform.render import render

    render(tpl, {}, out)
    text = load_pages(out)[0].text()
    # 版面與欄位名還在，但值不見了
    assert "比較法調查估價表" in text
    assert "184,763" not in text
    assert "212,958" not in text
