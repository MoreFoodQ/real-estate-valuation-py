"""區域因素規則集（28 項）測試。

表5-2 在 Golden Case 裡全部是 0.00%，所以**測不到矩陣查表**——
比準地與比較標的同區段，等級兩兩相同，一個壞掉的矩陣也會碰巧全對。
因此這裡測的是別的東西：級距的邊界、方向、以及三種特殊語意
（區段內有 / 或無 / 多設施），這些才是區域因素真正容易寫錯的地方。

矩陣本身由 validator 的 `max_range == 矩陣[優][劣]` 交叉校驗把關：
max_range 是 PDF 上另外獨立印出的黃底數字，等於用兩個來源互相驗證 28 個 step。
"""

import pytest

from src.classify import classify
from src.ruleset import load_moi_caps, load_ruleset
from src.validate import check_ruleset, errors, warnings

REG = load_ruleset("jinshan_commercial_regional")


def test_all_twenty_eight_factors_encoded():
    assert len(REG) == 28
    assert REG.meta["completeness"]["encoded"] == 28
    assert REG.meta["status"] == "complete"


def test_ruleset_self_check_is_clean():
    """0 ERROR 代表級距無縫隙／無重疊、矩陣反對稱、max_range 與矩陣一致。"""
    findings = check_ruleset(REG)
    assert errors(findings) == []
    assert warnings(findings) == []


def test_all_eight_groups_are_present():
    groups = {f.group for f in REG.factors.values()}
    assert groups == {
        "土地使用管制(1)",
        "交通運輸(2)",
        "自然條件(3)",
        "公共建設(4)",
        "特殊設施(5)",
        "環境污染(6)",
        "工商活動(7)",
    }


# ---------- 「區段內有」是一種級距語意，不是距離 0 ----------


def test_in_segment_is_the_best_grade():
    g = classify(REG["regional.public.market"], "區段內有")
    assert (g.grade, g.label) == (1, "優")


def test_zero_distance_is_not_the_same_as_in_segment():
    """這是設計「區段內有」時最重要的一條：不能用距離 0 代表它。

    0 也落在下一級的「未滿500m」裡，兩者會撞在一起——用 0 表示區段內，
    會讓最優級永遠取不到，而錯誤剛好落在「差一級」這種最難用眼睛看出來的地方。
    """
    assert classify(REG["regional.public.market"], 0).grade == 2
    assert classify(REG["regional.public.market"], "區段內有").grade == 1


def test_in_segment_rejected_when_the_factor_has_no_such_grade():
    """嫌惡設施沒有「區段內有」這一級（優是 3,000m以上）。

    誤把嫌惡設施當成正面設施餵進「區段內有」時要當場報錯，不能默默判成優——
    那會把「殯儀館就在隔壁」算成最好的情形。
    """
    with pytest.raises(ValueError, match="區段內有"):
        classify(REG["regional.special.funeral"], "區段內有")


# ---------- 「無」的方向：正面設施與嫌惡設施相反 ----------


def test_absent_is_worst_for_a_positive_facility():
    """沒有百貨公司 → 劣。條文明文寫「1,500m以上或無」。"""
    g = classify(REG["regional.commerce.department_store"], None)
    assert g.grade == 5


def test_absent_is_best_for_a_nuisance():
    """沒有廢棄物處理設施 → 優。方向與正面設施相反。

    這一項的條文**沒有**寫「或無」，是依 Golden Case 反推的（表1 三個選項
    全未圈選、表5-2 填 1 優）。規則裡標了 inferred，待地政局確認。
    """
    g = classify(REG["regional.special.waste"], "無")
    assert g.grade == 1
    band = REG["regional.special.waste"].classifier["bands"][0]
    assert band["inferred"] is True
    assert "需向地政局確認" in band["source_defect"]


def test_absent_interchange_is_worst_not_best():
    """交流道是正面設施：沒有交流道 → 劣。

    它與嫌惡設施同樣沒有「或無」條文，但方向相反。這兩條放在一起，
    是為了防止有人日後「統一」成同一種處理方式。
    """
    assert classify(REG["regional.transport.interchange"], "無交流道".replace("無交流道", "無")).grade == 5
    assert classify(REG["regional.special.utility"], "無").grade == 1


# ---------- 級距邊界 ----------


@pytest.mark.parametrize(
    "factor_id,value,expected",
    [
        # 白話說明的主角：18m 只能是普通，不能是稍優
        ("regional.transport.main_road_width", 18, 3),
        ("regional.transport.main_road_width", 20, 2),
        ("regional.transport.main_road_width", 15, 3),
        ("regional.transport.main_road_width", 14.99, 4),
        # 防混用：同一個數值在區域與個別因素判不同級
        ("regional.land_control.building_coverage", 70, 1),
        ("regional.land_control.floor_area_ratio", 240, 1),
        # 嫌惡設施方向相反：越遠越好
        ("regional.special.utility", 440, 5),
        ("regional.special.utility", 700, 4),
        ("regional.special.utility", 3000, 1),
        # 正面設施：越近越好
        ("regional.public.parking", 120, 2),
        ("regional.commerce.financial", 210, 2),
        ("regional.commerce.exhibition_hotel", 850, 3),
        ("regional.transport.large_station", 300, 1),
        # 百分比型
        ("regional.commerce.shop_continuity", 90, 1),
        ("regional.commerce.shop_continuity", 80, 1),
        ("regional.commerce.shop_continuity", 79.99, 2),
    ],
)
def test_band_boundaries(factor_id, value, expected):
    assert classify(REG[factor_id], value).grade == expected


def test_text_categories():
    cases = {
        "regional.land_control.urban_plan": ("都市計畫內", 1),
        "regional.land_control.zoning": ("第二種商業區", 1),
        "regional.land_control.build_prohibition": ("無", 1),
        "regional.nature.drainage": ("有排水系統不易淹水", 2),
        "regional.nature.terrain": ("該區地勢平坦", 1),
        "regional.transport.road_development": ("已完全開發", 1),
        "regional.commerce.customer_traffic": ("顧客通行量多", 1),
    }
    for factor_id, (value, expected) in cases.items():
        assert classify(REG[factor_id], value).grade == expected, factor_id


# ---------- 多設施取最近 ----------


def test_nearest_of_multiple_facilities_matches_the_official_sample():
    """手冊 p.24「以對當地地價影響最大者填寫」＝取最近。

    對嫌惡設施而言最近的最糟，對正面設施而言最近的最好，兩邊都是取最近，
    所以這條規則不必分方向。Golden Case 兩個佐證：
    - 電業：變電所 700m、儲油槽 440m → 取 440m → 劣，表5-2 填 5 ✓
    - 殯葬：公墓 80m、納骨塔 750m → 取 80m → 劣，表5-2 填 5 ✓
    """
    assert classify(REG["regional.special.utility"], min(700, 440)).grade == 5
    assert classify(REG["regional.special.funeral"], min(80, 750)).grade == 5
    # 若取最遠會得到不同答案，表示這條規則真的有分辨力
    assert classify(REG["regional.special.utility"], max(700, 440)).grade == 4


# ---------- 原始資料的瑕疵 ----------


def test_two_source_defects_are_recorded_not_silently_fixed():
    """基準表有兩處單位誤植（200km、1,000km）。

    修正值有註記、原始 PDF 保留為證據——不能默默改掉，那等於湮滅了
    「這本表本身有問題」這個發現。
    """
    bus = REG["regional.transport.bus_stop"].classifier["bands"][2]
    assert bus["min"] == 200 and "200km" in bus["source_defect"]

    tourism = REG["regional.public.tourism"].classifier["bands"][3]
    assert tourism["min"] == 1000 and "1,000km" in tourism["source_defect"]


# ---------- 內政部上限（附件24） ----------


def test_compliant_with_moi_cap_under_the_declared_column():
    """附件24 的商業用地分四級，本表未載明屬何者，由規則集宣告並說明理由。"""
    assert REG.meta["moi_cap_column"] == "普通商業用地"
    assert warnings(check_ruleset(REG)) == []


def test_classification_changes_the_compliance_verdict():
    """歸類不同，合規結論就不同——這正是必須向地政局確認的原因。

    村里鄰商業用地的上限較嚴，本表會有 5 項超標；高度商業用地的交流道
    上限只有 5%，本表訂 8% 也會超標。中度與普通則全數合規。
    """
    caps = load_moi_caps(kind="regional")["caps"]

    def over(column):
        return {
            fid
            for fid in REG.factor_ids
            if REG[fid].max_range > caps[fid][column]
        }

    assert over("普通商業用地") == set()
    assert over("中度商業用地") == set()
    assert over("高度商業用地") == {"regional.transport.interchange"}
    assert over("村里鄰商業用地") == {
        "regional.public.park",
        "regional.pollution.environmental",
        "regional.commerce.department_store",
        "regional.commerce.exhibition_hotel",
        "regional.commerce.shop_continuity",
    }


def test_non_numeric_value_raises_a_clean_error():
    """數值型細項收到文字時要丟 ValueError，不能讓 Decimal 的 InvalidOperation 漏出去。

    InvalidOperation 是 ArithmeticError 的子類、不是 ValueError，呼叫端的
    `except ValueError` 接不住，會一路變成 HTTP 500——而 500 走 Starlette
    最外層的 middleware，拿不到 CORS 標頭，瀏覽器只看得到一句看不出原因的
    CORS 錯誤。實際踩過這個坑。
    """
    with pytest.raises(ValueError, match="無法解析為數字"):
        classify(REG["regional.special.waste"], "埋場")
