"""RuleSet 自檢測試。

兩件事：
1. 兩份規則檔都不得有 ERROR（級距缺口／重疊、矩陣不對稱、max_range 抄錯…）。
2. 已知的合規問題必須被 WARN 抓到，而且不能被自動修正掉。
"""

import pytest

from src.ruleset import load_moi_caps, load_ruleset
from src.validate import check_ruleset, errors, warnings

IND = load_ruleset("jinshan_commercial_individual")
REG = load_ruleset("jinshan_commercial_regional")
CAPS = load_moi_caps()


@pytest.mark.parametrize("rs", [IND, REG], ids=["individual", "regional"])
def test_no_structural_errors(rs):
    found = errors(check_ruleset(rs))
    assert found == [], "\n".join(str(f) for f in found)


def test_road_type_exceeds_moi_cap_and_is_only_a_warning():
    """已驗證的合規缺口：金山商業個別因素「道路種類」最大幅度 8%，
    超出內政部附件25 商業用地上限 5%。

    必須是 WARN 而非 ERROR，也不能自動夾到 5%——
    因為 Golden Case 的 +2.00% 正是用 step=2.0（即 max 8）算出來的，
    自動修正會導致無法重現官方答案。
    """
    found = check_ruleset(IND)
    exceeded = [f for f in found if f.code == "MOI_CAP_EXCEEDED"]
    assert len(exceeded) == 1
    f = exceeded[0]
    assert f.factor_id == "individual.road.road_type"
    assert f.level == "WARN"
    assert "8" in f.message and "5" in f.message

    # 規則檔本身未被修改
    assert IND["individual.road.road_type"].max_range == 8
    assert IND["individual.road.road_type"].compliance_note is not None


def test_all_other_factors_are_within_moi_cap():
    found = warnings(check_ruleset(IND))
    unexpected = [f for f in found if f.code == "MOI_CAP_EXCEEDED"
                  and f.factor_id != "individual.road.road_type"]
    assert unexpected == [], "\n".join(str(f) for f in unexpected)


def test_moi_caps_cover_all_encoded_individual_factors():
    missing = [fid for fid in IND.factor_ids if fid not in CAPS["caps"]]
    assert missing == [], f"內政部上限表缺少：{missing}"


def test_grade_labels_use_official_wording():
    assert IND.grade_labels[5] == ["優", "稍優", "普通", "稍劣", "劣"]
    assert IND.grade_labels[3] == ["優", "普通", "劣"]
    assert IND.grade_labels[2] == ["優", "劣"]


def test_dynamic_grade_count_is_supported():
    """地勢是 3 級、形狀/停車/禁限建是 2 級，其餘 5 級。
    引擎必須動態處理 N，不可寫死 5×5。"""
    counts = {f.grade_count for f in IND.factors.values()}
    assert counts == {2, 3, 5}
    assert IND["individual.parcel.terrain"].grade_count == 3
    assert IND["individual.parcel.shape"].grade_count == 2


def test_detects_injected_band_gap():
    """故意戳一個級距缺口，validator 必須抓到。"""
    f = IND["individual.parcel.area"]
    original = f.classifier["bands"]
    f.classifier["bands"] = [
        {"grade": 1, "min": 93},
        {"grade": 2, "min": 85, "max": 93},  # 原為 83，製造 83~85 缺口
        {"grade": 3, "min": 73, "max": 83},
        {"grade": 4, "min": 63, "max": 73},
        {"grade": 5, "max": 63},
    ]
    try:
        found = errors(check_ruleset(IND))
        assert any(x.code == "BAND_GAP" for x in found), [str(x) for x in found]
    finally:
        f.classifier["bands"] = original


def test_detects_injected_max_range_mismatch():
    """故意把 step 抄錯，max_range 交叉驗證必須抓到。"""
    f = IND["individual.parcel.width"]
    original = dict(f.matrix)
    f.matrix["step"] = 1.5  # max_range 是 4，step 1.5 會得 6
    try:
        found = errors(check_ruleset(IND))
        assert any(x.code == "MAX_RANGE_MISMATCH" for x in found)
    finally:
        f.matrix.clear()
        f.matrix.update(original)
