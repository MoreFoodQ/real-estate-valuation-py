"""RuleSet 自檢。

抓的是「規則本身壞了」，不是「案件算錯了」。
分兩級：ERROR = 引擎不能用；WARN = 可以跑但需人工確認（例如超出內政部上限）。

重要設計決定：超出內政部最大影響範圍只發 WARN、不自動修正。
因為官方 Golden Case 的道路種類 +2.00% 就是用超標的 step=2.0 算出來的，
自動夾到上限會導致無法重現官方答案。合規問題要回報給地政局，不是偷偷改。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .matrix import matrix_cells
from .ruleset import Factor, RuleSet, dec, load_moi_caps

UNIT_WHITELIST = {None, "m", "m2", "percent"}


@dataclass(frozen=True)
class Finding:
    level: str  # "ERROR" | "WARN"
    factor_id: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.factor_id} {self.code}: {self.message}"


def _check_bands(f: Factor) -> list[Finding]:
    out: list[Finding] = []
    c = f.classifier
    if c["type"] != "numeric_bands":
        return out

    intervals: list[tuple[Decimal, Decimal, int]] = []
    NEG, POS = Decimal("-1e18"), Decimal("1e18")
    for b in c["bands"]:
        ranges = b.get("or_ranges", [b])
        for r in ranges:
            # 純標記型級距（in_segment）沒有 min/max，不參與連續性檢查。
            # 把它當成 -∞~+∞ 會與每一級都重疊，發出一整排假的 BAND_OVERLAP。
            if r.get("min") is None and r.get("max") is None:
                continue
            lo = dec(r["min"]) if r.get("min") is not None else NEG
            hi = dec(r["max"]) if r.get("max") is not None else POS
            if lo >= hi:
                out.append(Finding("ERROR", f.factor_id, "BAND_INVERTED",
                                   f"第{b['grade']}級 min({r.get('min')}) >= max({r.get('max')})"))
            intervals.append((lo, hi, b["grade"]))

    intervals.sort()
    for (lo1, hi1, g1), (lo2, hi2, g2) in zip(intervals, intervals[1:]):
        if hi1 < lo2:
            out.append(Finding("ERROR", f.factor_id, "BAND_GAP",
                               f"第{g1}級與第{g2}級之間有缺口：{hi1} ~ {lo2} 無級距涵蓋"))
        elif hi1 > lo2:
            out.append(Finding("ERROR", f.factor_id, "BAND_OVERLAP",
                               f"第{g1}級與第{g2}級級距重疊於 {lo2} ~ {hi1}"))

    if intervals and intervals[0][0] != NEG:
        out.append(Finding("ERROR", f.factor_id, "BAND_UNBOUNDED_LOW",
                           "最低級距未涵蓋負無窮方向（缺「未滿X」級）"))
    if intervals and intervals[-1][1] != POS:
        out.append(Finding("ERROR", f.factor_id, "BAND_UNBOUNDED_HIGH",
                           "最高級距未涵蓋正無窮方向（缺「X以上」級）"))
    return out


def _check_grades(f: Factor) -> list[Finding]:
    out: list[Finding] = []
    c = f.classifier
    key = "bands" if c["type"] == "numeric_bands" else "categories"
    grades = sorted(x["grade"] for x in c[key])
    if grades != list(range(1, f.grade_count + 1)):
        out.append(Finding("ERROR", f.factor_id, "GRADE_SET",
                           f"等級應為 1..{f.grade_count} 各一次，實得 {grades}"))
    if len(f.grade_labels) != f.grade_count:
        out.append(Finding("ERROR", f.factor_id, "GRADE_LABELS",
                           f"grade_labels 數量 {len(f.grade_labels)} != grade_count {f.grade_count}"))
    return out


def _check_matrix(f: Factor) -> list[Finding]:
    out: list[Finding] = []
    try:
        cells = matrix_cells(f)
    except ValueError as e:
        return [Finding("ERROR", f.factor_id, "MATRIX_SHAPE", str(e))]

    n = f.grade_count
    for i in range(n):
        if cells[i][i] != 0:
            out.append(Finding("ERROR", f.factor_id, "MATRIX_DIAGONAL",
                               f"同級對同級應為 0，[{i+1}][{i+1}] = {cells[i][i]}"))
    for i in range(n):
        for j in range(n):
            if cells[i][j] != -cells[j][i]:
                out.append(Finding("ERROR", f.factor_id, "MATRIX_ASYMMETRY",
                                   f"[{i+1}][{j+1}]={cells[i][j]} 與 [{j+1}][{i+1}]={cells[j][i]} 非反對稱"))

    # 黃底最大值必須等於「優 vs 劣」極值，這是 PDF 上另外獨立印出的數字，
    # 可交叉驗證 step 是否抄錯。
    extreme = cells[0][n - 1]
    if extreme != f.max_range:
        out.append(Finding("ERROR", f.factor_id, "MAX_RANGE_MISMATCH",
                           f"max_range={f.max_range} 但矩陣[優][劣]={extreme}，step 可能抄錯"))
    return out


def _check_unit(f: Factor) -> list[Finding]:
    if f.unit not in UNIT_WHITELIST:
        return [Finding("ERROR", f.factor_id, "UNIT_UNKNOWN",
                        f"單位 {f.unit!r} 不在白名單 {UNIT_WHITELIST}（防 200m 被抽成 200km 之類的錯誤）")]
    return []


def _check_moi_cap(f: Factor, land_use: str, caps: dict) -> list[Finding]:
    entry = caps["caps"].get(f.factor_id)
    if entry is None:
        return [Finding("WARN", f.factor_id, "MOI_CAP_MISSING",
                        "內政部最大影響範圍表查無此細項，無法驗證合規")]
    cap = entry.get(land_use)
    if cap is None:
        return [Finding("WARN", f.factor_id, "MOI_CAP_NA",
                        f"內政部規定 {land_use} 此項「不予考慮調整」，但自訂表仍訂了 {f.max_range}%")]
    if f.max_range > dec(cap):
        return [Finding("WARN", f.factor_id, "MOI_CAP_EXCEEDED",
                        f"自訂表最大修正幅度 {f.max_range}% 超出內政部 {land_use} 上限 {cap}%"
                        f"（{entry['label']}，{caps['source']['appendix']}）。"
                        f"依查估辦法第20條第2項應在上限內；本引擎僅警告不修正，"
                        f"以維持官方 Golden Case 可重現性。")]
    return []


def check_ruleset(rs: RuleSet, *, moi_caps: dict | None = None) -> list[Finding]:
    kind = rs.scope.get("factor_kind", "individual")
    caps = moi_caps if moi_caps is not None else load_moi_caps(kind=kind)

    # 區域因素的上限欄不是用地別，而是商業用地的四個細分級（高度／中度／
    # 普通／村里鄰）。這個歸類不在基準表上，由規則集自己宣告並說明理由。
    land_use = rs.meta.get("moi_cap_column") or rs.scope.get("land_use", "")

    findings: list[Finding] = []
    for f in rs.factors.values():
        findings += _check_grades(f)
        findings += _check_bands(f)
        findings += _check_matrix(f)
        findings += _check_unit(f)
        findings += _check_moi_cap(f, land_use, caps)
    return findings


def errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == "ERROR"]


def warnings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == "WARN"]
