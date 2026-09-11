"""表1 地價區段勘查表 辨識器測試。

表1 是三張表裡最難的，測試重點放在版面陷阱上——這些是實測踩到、
而且只要有人「順手簡化」就會再犯的：

- 直排標籤（`大型車⏎站`、`電⏎業⏎氣⏎體⏎燃⏎料`）
- 等級落在標籤的下一列（市場、廢棄物處理）
- 同一列左右面板各有一組等級（交流道 vs 殯葬）
- 級數不一定是 5（都市計畫內外、有無禁建、有無限建都是 2 級）
- 多設施要能各自對上自己的距離（殯葬取最劣 80m、電業取最劣 440m）
"""

from __future__ import annotations

import json

import pytest

import paths
from parser.detect import find_page
from parser.extract import load_pages
from parser.table1 import TABLE1_ROWS, parse, parse_survey_cell


@pytest.fixture(scope="module")
def pages():
    return load_pages(paths.require(paths.SAMPLE_FORMS_PDF))


@pytest.fixture(scope="module")
def parsed(pages):
    return parse(find_page(pages, "表1"))


@pytest.fixture(scope="module")
def golden():
    with open(
        paths.ROOT / "parser" / "golden" / "table5_2_1140901_99_001.json",
        encoding="utf-8",
    ) as f:
        return json.load(f)


# ---------- 表頭 ----------


def test_header(parsed):
    assert parsed.period == "1140901"
    assert parsed.segment_no == "P002-00"
    assert parsed.segment_scope is not None
    assert "金包里街" in parsed.segment_scope


# ---------- 28 個細項 ----------


def test_all_twenty_eight_factors_found(parsed):
    """一個都不能漏，而且不能有警告。

    範本是官方已填的正確件，辨識器對它應該完全沒有疑義；
    有警告就是辨識邏輯的問題，不是資料的問題。
    """
    assert len(TABLE1_ROWS) == 28
    assert parsed.warnings == []
    assert len(parsed.grades) == 28
    assert set(parsed.grades) == {fid for _, _, fid in TABLE1_ROWS}


def test_vertical_labels_are_matched(parsed):
    """五個直排標籤在網格裡是逐字換行的，比對前必須先把換行拿掉。"""
    for factor_id in (
        "regional.transport.large_station",
        "regional.special.utility",
        "regional.special.funeral",
        "regional.special.waste",
        "regional.pollution.environmental",
    ):
        assert parsed.grades[factor_id]["grade"] is not None, factor_id


def test_grade_can_sit_on_the_next_row(parsed):
    """市場的標籤在 r31、等級 `1 5` 在 r32；廢棄物處理的標籤在 r18、等級在 r19。

    跨列儲存格的文字畫在垂直置中處，會被切到相鄰網格列。
    只看同一列的話這兩項會整個抓不到。
    """
    assert parsed.grades["regional.public.market"]["grade"] == 1
    assert parsed.grades["regional.special.waste"]["grade"] == 1


def test_left_and_right_panels_do_not_steal_each_other(parsed):
    """r14 左邊是交流道 5/5、右邊是殯葬 5/5，兩者都要各自取到。"""
    assert parsed.grades["regional.transport.interchange"]["grade"] == 5
    assert parsed.grades["regional.special.funeral"]["grade"] == 5


def test_grade_count_is_not_always_five(parsed):
    """三個二級制的細項。把級數寫死成 5 會讓它們的等級語意整個錯掉。"""
    two_level = {
        "regional.land_control.urban_plan",
        "regional.land_control.build_prohibition",
        "regional.land_control.build_restriction",
    }
    for factor_id, cell in parsed.grades.items():
        expected = 2 if factor_id in two_level else 5
        assert cell["grade_count"] == expected, factor_id


# ---------- 與表5-2 交叉一致（手冊審查重點第 vi 項） ----------


def test_grades_match_table5_2(parsed, golden):
    """表1 的等級必須與表5-2 所載一致，28 項逐一比對。

    這是三層檢核的第二層，也是官方審查清單第 vi 項的原文要求：
    「影響地價區域因素分析明細表之修正細項優劣等級與各該地價區段勘查表
    所載內容一致」。
    """
    got = {fid: cell["grade"] for fid, cell in parsed.grades.items()}
    expected = {fid: grade for fid, (grade, _label) in golden["grades"].items()}
    assert got == expected


# ---------- 量測值 ----------


def test_numeric_measurements(parsed):
    """能直接讀成數字的量測值。這些是第一層檢核（量測值 vs 等級）的原料。"""
    surveys = parsed.surveys
    assert surveys["regional.land_control.building_coverage"]["numeric"] == 70
    assert surveys["regional.land_control.floor_area_ratio"]["numeric"] == 240
    assert surveys["regional.transport.main_road_width"]["numeric"] == 18
    assert surveys["regional.transport.avg_road_width"]["numeric"] == 12
    assert surveys["regional.commerce.shop_continuity"]["numeric"] == 90


def test_main_road_width_is_eighteen_metres(parsed):
    """18m 這個值是整份範本最重要的量測值之一：白話說明拿它當範例
    （「量到 18 米卻打成稍優」是錯法一），而區域因素基準表的級距是
    「普通：15m以上未滿20m」，所以 18 → 3 普通。表1 上印的正是 3。
    """
    assert parsed.surveys["regional.transport.main_road_width"]["numeric"] == 18
    assert parsed.grades["regional.transport.main_road_width"]["grade"] == 3


def test_text_measurements(parsed):
    surveys = parsed.surveys
    assert surveys["regional.land_control.urban_plan"]["text"] == "都市計畫內"
    assert surveys["regional.land_control.zoning"]["text"] == "第二種商業區"
    assert surveys["regional.nature.drainage"]["text"] == "有排水系統不易淹水"
    assert surveys["regional.transport.road_development"]["text"] == "已完全開發"


def test_selected_facility_with_distance(parsed):
    """圈選型欄位：四個車站選項裡只有一個是 ●，要取到它的名稱與距離。"""
    entries = parsed.surveys["regional.transport.large_station"]["entries"]
    marked = [e for e in entries if e["marked"]]
    assert len(marked) == 1
    assert marked[0]["option"] == "國光客運金山站"
    assert marked[0]["distance_m"] == 300
    assert marked[0]["in_segment"] is False


def test_multiple_facilities_keep_their_own_distances(parsed):
    """一個細項對應多個設施時，每個設施要各自帶著自己的距離。

    規則是取最劣（手冊 p.24「以對當地地價影響最大者填寫」），
    配對錯了就會取錯那一個：
    - 殯葬：墓地 80m、納骨塔 750m → 取 80m → 劣
    - 電業：金山變電所 700m、中油金山站 440m → 取 440m → 劣
    兩項在表5-2 上都填「5 劣」，與取最劣的結果一致。
    """
    funeral = [
        e for e in parsed.surveys["regional.special.funeral"]["entries"] if e["marked"]
    ]
    assert {(e["option"], e["distance_m"]) for e in funeral} == {
        ("墓地", 80),
        ("納骨塔", 750),
    }
    assert min(e["distance_m"] for e in funeral) == 80

    utility = [
        e for e in parsed.surveys["regional.special.utility"]["entries"] if e["marked"]
    ]
    assert {(e["name"], e["distance_m"]) for e in utility} == {
        ("金山變電所", 700),
        ("中油金山站", 440),
    }
    assert min(e["distance_m"] for e in utility) == 440


def test_absent_facility_keeps_its_name(parsed):
    """交流道欄兩個圈都沒點，但名稱寫了「無交流道」——「無」本身就是事實。

    這一項在表5-2 填 5 劣，正是因為沒有交流道。把未圈選的行丟掉，
    就無從說明這個 5 是怎麼來的。
    """
    entries = parsed.surveys["regional.transport.interchange"]["entries"]
    assert any(e["name"] == "無交流道" for e in entries)
    assert parsed.grades["regional.transport.interchange"]["grade"] == 5


def test_quantity_is_separated_from_name(parsed):
    """工商活動類的欄位是「名稱：X 數量:N」，兩者要分開。"""
    entries = parsed.surveys["regional.commerce.financial"]["entries"]
    named = [e for e in entries if e["name"]]
    assert named[0]["name"] == "新北市金山地區農會"
    assert named[0]["quantity"] == 1
    assert named[0]["distance_m"] == 210


def test_raw_text_is_always_preserved(parsed):
    """每一格都保留原文。這張表的欄位型態太雜，任何結構化都可能漏掉某種寫法，
    原文留著才能保證 UI 永遠顯示得出估價師實際寫了什麼。
    """
    for factor_id, survey in parsed.surveys.items():
        assert "raw" in survey
        assert isinstance(survey["raw"], str)


# ---------- 值解析器單元測試 ----------


def test_location_marker_is_not_an_option():
    """「●本區段外(距 300 M)」是位置標記，不是選項。

    不濾掉的話，「●金山區第一零售傳統市場 ●本區段內」會被算成兩個選項。
    """
    got = parse_survey_cell("●國光客運金山站 ○本區段內 ●本區段外(距 300 M)")
    assert len(got["entries"]) == 1
    assert got["entries"][0]["option"] == "國光客運金山站"


def test_distance_is_not_mistaken_for_a_measurement():
    """距離已經在 entries 裡，不能再被當成這一欄的量測值。"""
    got = parse_survey_cell("名稱：金山變電所 ○本區段內 ●本區段外(距 700 M)")
    assert got["numeric"] is None
    assert got["entries"][0]["distance_m"] == 700


def test_checkbox_cells_have_no_plain_text(parsed):
    """有圈選框的格子不該產生「純文字填答」。

    那些不含 ○● 的行都是被排版折斷的選項標籤碎片：
    「○垃圾場或掩／埋場」的下半段是「埋場」、「變電所或高壓／鐵塔」的下半段是「鐵塔」。
    當成填答會在畫面上顯示「埋場」這種看不懂的值，而真正的事實在 entries 裡。
    """
    for factor_id in (
        "regional.special.waste",
        "regional.special.utility",
        "regional.pollution.environmental",
    ):
        assert parsed.surveys[factor_id]["text"] is None, factor_id

    # 沒有圈選框的格子則必須留住填答文字。
    assert parsed.surveys["regional.nature.drainage"]["text"] == "有排水系統不易淹水"
    assert parsed.surveys["regional.transport.road_development"]["text"] == "已完全開發"
