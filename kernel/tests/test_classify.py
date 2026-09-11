"""分級單元測試。

最重要的是「防混用」四個：同一個數值在區域因素與個別因素判出不同等級。
這四個測試一旦被寫死，就不可能把兩套規則接錯。
"""

import pytest

from src.classify import classify, classify_worst
from src.ruleset import load_ruleset

IND = load_ruleset("jinshan_commercial_individual")
REG = load_ruleset("jinshan_commercial_regional")


# ---------- 區域因素 ----------

def test_regional_main_road_18m_is_putong():
    g = classify(REG["regional.transport.main_road_width"], 18)
    assert (g.grade, g.label) == (3, "普通")
    assert "15m以上未滿20m" in g.reason


def test_regional_avg_road_12m_is_putong():
    g = classify(REG["regional.transport.avg_road_width"], 12)
    assert (g.grade, g.label) == (3, "普通")


def test_regional_drainage_text_is_shaoyou():
    g = classify(REG["regional.nature.drainage"], "有排水系統不易淹水")
    assert (g.grade, g.label) == (2, "稍優")


# ---------- 防混用：同名欄位不得共用規則 ----------

def test_building_coverage_70_regional_you_individual_shaoyou():
    r = classify(REG["regional.land_control.building_coverage"], 70)
    i = classify(IND["individual.admin.building_coverage"], 70)
    assert (r.grade, r.label) == (1, "優"), "區域因素 60% 以上即為優"
    assert (i.grade, i.label) == (2, "稍優"), "個別因素 70~80% 為稍優"
    assert r.grade != i.grade


def test_far_240_regional_you_individual_shaoyou():
    r = classify(REG["regional.land_control.floor_area_ratio"], 240)
    i = classify(IND["individual.admin.floor_area_ratio"], 240)
    assert (r.grade, r.label) == (1, "優"), "區域因素 240% 以上即為優"
    assert (i.grade, i.label) == (2, "稍優"), "個別因素 240~300% 為稍優"
    assert r.grade != i.grade


# ---------- 個別因素：邊界與方向 ----------

def test_depth_is_non_monotonic():
    f = IND["individual.parcel.depth"]
    assert classify(f, 23).grade == 3, "20~30m 為普通"
    assert classify(f, 16).grade == 4, "10~20m 為稍劣"
    assert classify(f, 60).grade == 1, "40~100m 為優"
    assert classify(f, 5).grade == 5, "未滿10m 為劣"
    assert classify(f, 150).grade == 5, "100m 以上同為劣（非單調）"


def test_nuisance_is_farther_better():
    f = IND["individual.surroundings.nuisance"]
    assert classify(f, 260).grade == 3
    assert classify(f, 80).grade == 5, "越近越劣，方向與接近條件相反"
    assert classify(f, 600).grade == 1
    assert classify(f, "無").grade == 1, "條文明文『500m以上或無』"


def test_station_is_nearer_better():
    f = IND["individual.proximity.station"]
    assert classify(f, 80).grade == 1
    assert classify(f, 190).grade == 1
    assert classify(f, 900).grade == 5
    assert classify(f, "無").grade == 5, "正面設施『無』為劣"


def test_parking_needs_exact_match_not_contains():
    f = IND["individual.surroundings.parking"]
    assert classify(f, "可路邊停車").grade == 1
    assert classify(f, "不可路邊停車").grade == 2, "『可路邊停車』是其子字串，contains 會誤判為優"


def test_zoning_needs_contains_match():
    f = IND["individual.admin.zoning"]
    assert classify(f, "第二種商業區").grade == 1, "實填『第二種商業區』須對上『商業區』"
    assert classify(f, "第二種住宅區").grade == 2


# ---------- 邊界值 ----------

@pytest.mark.parametrize(
    "value,expected",
    [(20, 1), (19.99, 2), (15, 2), (14.99, 3), (8, 3), (7.99, 4), (4, 4), (3.99, 5)],
)
def test_frontage_road_width_boundaries_are_min_inclusive(value, expected):
    """min 含、max 不含。20m 恰好落在『20m以上』的優。"""
    assert classify(IND["individual.road.frontage_road_width"], value).grade == expected


# ---------- 多設施取最劣 ----------

def test_multi_facility_takes_worst():
    """佐證：表1 電業設施 變電所700m(稍劣) + 儲油槽440m(劣) → 表5-2 填「劣」。

    以個別因素嫌惡設施代跑同一聚合邏輯（區域因素該項於 Step B 補上）。
    """
    g = classify_worst(IND["individual.surroundings.nuisance"], [700, 440])
    assert g.grade == 2, "700m→稍優(2)、440m→稍優(2)，取最劣仍為 2"
    g2 = classify_worst(IND["individual.surroundings.nuisance"], [600, 80])
    assert g2.grade == 5, "600m→優(1)、80m→劣(5)，取最劣為 5"


# ---------- 失敗路徑 ----------

def test_absent_without_or_absent_clause_raises():
    """區域因素排水沒有『或無』條文，值為無時必須明確報錯而不是猜。"""
    with pytest.raises(ValueError, match="不符合任何類別"):
        classify(REG["regional.nature.drainage"], "無")


def test_unknown_category_raises():
    with pytest.raises(ValueError, match="不符合任何類別"):
        classify(IND["individual.parcel.shape"], "三角形")
