"""壓力測試主程式。

每個案例獨立捕捉例外，記錄失敗型態而不中斷整體。輸出分三種標記：

  OK    正常完成（但要看說明——「沒爆掉」不等於「答案對」）
  RAISE 拋出例外，且型別是 ValueError（api 層接得住，會變成 4xx）
  !!    拋出非 ValueError 的例外（api 層接不住，會變成 500），
        或明顯的靜默錯誤

用法：python -m stress.audit
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import paths
from api.kernel_api import (
    RULES_DIR, appraise_table4, check_ruleset, classify, load_ruleset, lookup,
)
from api.review import review
from parser import table1, table4, table5_2
from parser.detect import detect_table, find_page
from parser.extract import load_pages
from src.validate import errors, warnings

PARSERS = {"表1": table1.parse, "表5-2": table5_2.parse, "表4": table4.parse}
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TMP = Path(__file__).resolve().parent / ".tmp"

rows: list[tuple[str, str, str, str]] = []


def record(group: str, case: str, outcome: str, note: object = "") -> None:
    rows.append((group, case, outcome, str(note)[:220].replace("\n", " ")))


def run(group: str, case: str, fn) -> None:
    try:
        record(group, case, "OK", fn())
    except ValueError as e:
        record(group, case, "RAISE ValueError", e)
    except Exception as e:  # noqa: BLE001 - 探索腳本刻意攔全部
        record(group, case, "!! " + type(e).__name__, e)


# ------------------------------------------------------------------ 基準

PDF = paths.require(paths.SAMPLE_FORMS_PDF)
PAGES = load_pages(PDF)
BASE: dict = {}
for _pg in PAGES:
    _c = detect_table(_pg)
    if _c and _c not in BASE:
        BASE[_c] = PARSERS[_c](_pg).to_dict()

RI = load_ruleset("jinshan_commercial_individual")
RR = load_ruleset("jinshan_commercial_regional")


def base() -> dict:
    return copy.deepcopy(BASE)


def rv(t: dict, rr=None) -> str:
    r = review(t, RI, rr or RR)
    sanity = r.get("sanity") or []
    errs = sum(1 for s in sanity if s.get("level") == "error")
    # 可疑值一定要印出來。合理性檢查存在的理由就是「verdict=match 但輸入不可信」，
    # 如果報告只看 verdict，這個能力等於沒被測到。
    tail = " 可疑=%d(error %d)" % (len(sanity), errs) if sanity else ""
    return "verdict=%s 不符=%d 查=%d 查不動=%d%s" % (
        r["verdict"], r["finding_count"], r["checked_total"],
        len(r["not_checkable"]), tail,
    )


# ------------------------------------------------------------------ A 缺表

for keep in (
    ("表1",), ("表5-2",), ("表4",),
    ("表1", "表5-2"), ("表1", "表4"), ("表5-2", "表4"),
    ("表1", "表5-2", "表4"),
):
    run("A 缺表", "只有 " + "+".join(keep),
        lambda keep=keep: rv({k: v for k, v in base().items() if k in keep}))


# ------------------------------------------------------------- B 標的數與權重

def n_comparables(n: int, weight):
    t = base()
    c0 = t["表4"]["comparables"][0]
    t["表4"]["comparables"] = []
    for i in range(n):
        c = copy.deepcopy(c0)
        c["index"] = i + 1
        c["weight_pct"] = weight if not isinstance(weight, list) else weight[i]
        c["normal_unit_price"] = 184763 + i * 10000
        t["表4"]["comparables"].append(c)
    res = appraise_table4(RI, t["表4"])
    return "比較價格=%s 地價=%s 權重=%s" % (
        res.benchmark_comparison_price, res.benchmark_land_price,
        [str(x.weight_pct) for x in res.comparables],
    )


for n in (0, 1, 2, 3, 4):
    run("B 標的數", "%d 件，權重留空由系統決定" % n,
        lambda n=n: n_comparables(n, None))

for w in ([70, 30], [50, 30, 20], [60, 40]):
    run("B 標的數", "%d 件，權重 %s（合計 100）" % (len(w), w),
        lambda w=w: n_comparables(len(w), w))

# 真實表單四捨五入後常見的 99% / 101%
for w in ([70, 29], [70, 31], [33, 33, 33]):
    run("B 標的數", "%d 件，權重 %s（合計 %d）" % (len(w), w, sum(w)),
        lambda w=w: n_comparables(len(w), w))


# ------------------------------------------------------------------ C 數值

for label, val in (
    ("0", 0), ("負數", -184763), ("極大 1e12", 10**12), ("小數", 184763.456),
    ("字串數字", "184763"), ("帶千分位字串", "184,763"),
    ("非數字字串", "無"), ("空字串", ""), ("None", None),
):
    def _price(val=val):
        t = base()
        t["表4"]["comparables"][0]["normal_unit_price"] = val
        res = appraise_table4(RI, t["表4"])
        return "地價=%s ｜ %s" % (res.benchmark_land_price, rv(t))
    run("C 數值", "表4 單價 = %s" % label, _price)

for label, val in (
    ("跨到最劣級 20", 20), ("負面積", -50), ("零", 0),
    ("非數字", "約一百坪"), ("None", None), ("空字串", ""),
):
    def _area(val=val):
        t = base()
        t["表4"]["comparables"][0]["facts"]["individual.parcel.area"] = val
        return rv(t)
    run("C 數值", "表4 面積 = %s" % label, _area)

for label, val in (("超出上界 9", 9), ("零", 0), ("負 -1", -1),
                   ("字串 '3'", "3"), ("None", None)):
    def _grade(val=val):
        t = base()
        t["表1"]["grades"]["regional.transport.main_road_width"]["grade"] = val
        return rv(t)
    run("C 數值", "表1 等級 = %s" % label, _grade)


# ------------------------------------------------------------------ D 規則集

RAW_R = json.loads((RULES_DIR / "jinshan_commercial_regional.json").read_text("utf-8"))
TMP.mkdir(parents=True, exist_ok=True)


def with_mutation(mut) -> str:
    raw = copy.deepcopy(RAW_R)
    mut(raw)
    p = TMP / "mutated.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    rs = load_ruleset(p)
    found = check_ruleset(rs)
    return "載入成功 factors=%d 自檢ERROR=%d → %s" % (
        len(rs), len(errors(found)), rv(base(), rs))


MUTATIONS = (
    ("刪掉一個 factor", lambda r: r["factors"].pop()),
    ("只留 3 個 factor", lambda r: r.__setitem__("factors", r["factors"][:3])),
    ("factors 空陣列", lambda r: r.__setitem__("factors", [])),
    ("刪掉 grade_labels", lambda r: r.pop("grade_labels")),
    ("刪掉 scope", lambda r: r.pop("scope")),
    ("刪掉 ruleset_id", lambda r: r.pop("ruleset_id")),
    ("factor 缺 max_range", lambda r: r["factors"][0].pop("max_range")),
    ("factor 缺 matrix", lambda r: r["factors"][0].pop("matrix")),
    ("factor 缺 classifier", lambda r: r["factors"][0].pop("classifier")),
    ("grade_count=7（無對應 labels）",
     lambda r: r["factors"][0].__setitem__("grade_count", 7)),
    ("factor_id 改名", lambda r: r["factors"][0].__setitem__("factor_id", "regional.x.unknown")),
    ("matrix kind 改成不支援值",
     lambda r: r["factors"][0]["matrix"].__setitem__("kind", "magic")),
    ("classifier type 改成不支援值",
     lambda r: r["factors"][0]["classifier"].__setitem__("type", "magic")),
)

for label, mut in MUTATIONS:
    run("D 規則集", label, lambda mut=mut: with_mutation(mut))


def _hole(r):
    for f in r["factors"]:
        if f["factor_id"] == "regional.land_control.building_coverage":
            f["classifier"]["bands"].pop(2)


def _overlap(r):
    for f in r["factors"]:
        if f["factor_id"] == "regional.land_control.building_coverage":
            f["classifier"]["bands"][1]["min"] = 30


run("D 規則集", "級距挖洞（建蔽率移除第3級）", lambda: with_mutation(_hole))
run("D 規則集", "級距重疊（建蔽率）", lambda: with_mutation(_overlap))


# 合成規則集（需先跑 make_rulesets）
for f in sorted(FIXTURES.glob("*.json")) if FIXTURES.exists() else []:
    def _fixture(f=f):
        rs = load_ruleset(f)
        found = check_ruleset(rs)
        return "自檢ERROR=%d WARN=%d → %s" % (
            len(errors(found)), len(warnings(found)), rv(base(), rs))
    run("D 規則集", "合成規則集 %s" % f.stem, _fixture)


# ------------------------------------------------------------------ E 產表

def _roundtrip():
    from pdfform.forms import build_forms
    out = TMP / "forms"
    out.mkdir(parents=True, exist_ok=True)
    written = build_forms(PDF, out, regional=RR, individual=RI,
                          appraise=appraise_table4, classify=classify, lookup=lookup)
    made = written.get("表4")
    if made is None:
        return "!! 沒有產出表4"
    pgs = load_pages(made)
    codes = [detect_table(p) for p in pgs]
    if "表4" not in codes:
        return "!! 產出的表4 再讀回來認不出表別，codes=%s" % codes
    again = table4.parse(pgs[codes.index("表4")]).to_dict()
    orig = BASE["表4"]
    return "重讀成功；價格一致=%s；facts=%d（原 %d）" % (
        again.get("benchmark_comparison_price") == orig.get("benchmark_comparison_price"),
        len(again["comparables"][0]["facts"]) if again["comparables"] else 0,
        len(orig["comparables"][0]["facts"]),
    )


run("E 產表", "parse → fill → render → 再 parse", _roundtrip)


def _forms_missing_table():
    """表4 跨頁時，產表路徑會不會整張跳過？"""
    from pdfform.forms import _find
    dup = PAGES + [p for p in PAGES if detect_table(p) == "表4"]
    found = {c: _find(dup, c) for c in ("表1", "表5-2", "表4")}
    got = {c: (p.number if p else "跳過") for c, p in found.items()}
    api_side = sorted({detect_table(p) for p in dup} - {None})
    return "產表路徑=%s ／ 辨識路徑=%s（不一致）" % (got, api_side)


run("E 產表", "表4 重複出現時，產表 vs 辨識的落差", _forms_missing_table)


# ------------------------------------------------------------------ F 偵測

run("F 偵測", "同一張表出現在多頁",
    lambda: find_page(PAGES + [p for p in PAGES if detect_table(p) == "表4"], "表4"))
run("F 偵測", "空的頁面清單", lambda: find_page([], "表4"))
run("F 偵測", "現有規則集自檢（regional）",
    lambda: "ERROR=%d WARN=%d" % (len(errors(check_ruleset(RR))), len(warnings(check_ruleset(RR)))))
run("F 偵測", "現有規則集自檢（individual）",
    lambda: "ERROR=%d WARN=%d" % (len(errors(check_ruleset(RI))), len(warnings(check_ruleset(RI)))))


# ------------------------------------------------------------------ 輸出

def main() -> int:
    print()
    print("=" * 120)
    print("壓力測試結果   共 %d 案" % len(rows))
    print("=" * 120)
    group = None
    for g, case, outcome, note in rows:
        if g != group:
            print()
            print("### " + g)
            group = g
        print("  %-44s %-20s %s" % (case[:44], outcome, note))

    hard = [r for r in rows if r[2].startswith("!!")]
    soft = [r for r in rows if r[2].startswith("RAISE")]
    print()
    print("=" * 120)
    print("OK %d ／ 拋 ValueError（api 接得住）%d ／ 非 ValueError 或靜默問題 %d"
          % (len(rows) - len(hard) - len(soft), len(soft), len(hard)))
    if hard:
        print()
        print("需要注意的：")
        for g, case, outcome, note in hard:
            print("  [%s] %s → %s %s" % (g, case, outcome, note[:120]))
    print()
    print("分析與修正優先序見 docs/ROBUSTNESS_AUDIT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
