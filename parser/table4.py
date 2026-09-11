"""表4 比較法調查估價表 辨識器。

先做表4 而不是表1，理由是**它是唯一已經有精確答案的表**：
`kernel/golden/case_1140901_99_001.json` 的 facts 就是期望輸出，不必先造 fixture。
而且它是錢的那條鏈，解出來立刻能端到端算到 212,958。

欄位定位一律靠框線，不靠文字順序也不靠標題中點：
「M」在 x=428、「差異率」標題在 x=446，取中點會把單位切到隔壁欄。
框線的單一邊最大跨距把欄界（≥247pt）與欄內子分隔線（≤105pt）分得很開，
所以用跨距篩出真正的欄界，再用標題文字認出哪一欄是誰。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .extract import Page, Word, bbox_of, find_label, words_at
from .provenance import FieldSource, Provenance

# 欄界判準：單一邊跨距下限。範本表4 實測欄界最小 247pt、欄內子分隔線最大 105pt。
EDGE_MIN_SPAN = 200.0
EDGE_MERGE_TOL = 3.0

# 標籤欄搜尋上界。標籤字串本身唯一，限制 x 只是避免誤中備註欄的長段文字。
LABEL_X_MAX = 200.0

NUM = "numeric"
PCT = "percent"
TEXT = "text"
NAMED_DIST = "named_distance"

# 表4 第 7～25 列 → kernel 的 19 個 individual.* factor_id。
# 這張對照表是資料不是邏輯，換書表版本只改這裡。
FACTOR_ROWS: tuple[tuple[str, str, str], ...] = (
    ("7面積(M2)", "individual.parcel.area", NUM),
    ("8寬度(M)", "individual.parcel.width", NUM),
    ("9深度(M)", "individual.parcel.depth", NUM),
    ("10形狀", "individual.parcel.shape", TEXT),
    ("11臨街情形", "individual.parcel.street_frontage", TEXT),
    ("12地勢", "individual.parcel.terrain", TEXT),
    ("13道路種類", "individual.road.road_type", TEXT),
    ("14面前道路寬度", "individual.road.frontage_road_width", NAMED_DIST),
    ("15接近學校之程度", "individual.proximity.school", NAMED_DIST),
    ("16接近市場之程度", "individual.proximity.market", NAMED_DIST),
    ("17接近公園、廣場之程度", "individual.proximity.park", NAMED_DIST),
    ("18接近車站之程度", "individual.proximity.station", NAMED_DIST),
    ("19接近商圈之程度", "individual.proximity.commercial_district", NAMED_DIST),
    ("20嫌惡設施(類型)", "individual.surroundings.nuisance", NAMED_DIST),
    ("21停車方便性", "individual.surroundings.parking", TEXT),
    ("22使用分區或編定用地", "individual.admin.zoning", TEXT),
    ("23建蔽率(%)", "individual.admin.building_coverage", PCT),
    ("24容積率(%)", "individual.admin.floor_area_ratio", PCT),
    ("25有無禁限建", "individual.admin.build_restriction", TEXT),
)

# factor_id → 表4 上的列名（含列號）。UI 顯示用，對照表留在後端。
FACTOR_LABELS: dict[str, str] = {fid: label for label, fid, _kind in FACTOR_ROWS}


@dataclass
class Table4:
    case_id: str
    appraisal_base_date: str
    benchmark: dict[str, Any]
    comparables: list[dict[str, Any]]
    benchmark_comparison_price: float | int | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "appraisal_base_date": self.appraisal_base_date,
            "benchmark": self.benchmark,
            "comparables": self.comparables,
            "benchmark_comparison_price": self.benchmark_comparison_price,
            "factor_labels": FACTOR_LABELS,
        }


# ---------- 欄界 ----------


def column_edges(page: Page, min_span: float = EDGE_MIN_SPAN) -> list[float]:
    """用框線的「單一邊最大跨距」篩出真正的欄界。

    不能用累計長度：同一條欄界常被畫成多個 rect，累計後與被畫了很多次的
    欄內子分隔線混在一起（範本表4 實測子分隔線累計可達 353pt）。
    """
    span: dict[float, float] = {}

    def note(x: float, height: float) -> None:
        key = round(x)
        span[key] = max(span.get(key, 0.0), height)

    for r in page.rects:
        h = abs(r["bottom"] - r["top"])
        note(r["x0"], h)
        note(r["x1"], h)
    for ln in page.lines:
        if abs(ln["x0"] - ln["x1"]) < 1.0:
            note(ln["x0"], abs(ln["bottom"] - ln["top"]))

    keep = sorted(x for x, h in span.items() if h >= min_span)
    merged: list[float] = []
    for x in keep:
        if merged and x - merged[-1] <= EDGE_MERGE_TOL:
            continue
        merged.append(float(x))
    return merged


def _cell_range(edges: list[float], word: Word) -> tuple[float, float]:
    """一個 word 落在哪一格（左右欄界）。"""
    lo = max((e for e in edges if e <= word.x0), default=edges[0])
    hi = min((e for e in edges if e >= word.x1), default=edges[-1])
    return (lo, hi)


@dataclass(frozen=True)
class Columns:
    """表4 的欄位座標。`comparables` 每筆是 (條件欄, 差異率欄)。"""

    benchmark: tuple[float, float]
    comparables: tuple[tuple[tuple[float, float], tuple[float, float]], ...]


def locate_columns(page: Page) -> Columns:
    """用表頭的「條件」／「差異率」文字認出各欄。

    表頭第一個「條件」是比準地（它沒有差異率欄——比準地不跟自己比），
    其後每一組（條件, 差異率）是一個比較標的。範本只填 1 件，
    但版面固定留 3 件，所以要能處理空欄。
    """
    edges = column_edges(page)
    if len(edges) < 4:
        raise ValueError("表4 框線不足，抓到的欄界只有 %s" % edges)

    headers = sorted(
        (w for w in page.words if w.text in ("條件", "差異率") and w.top < 65),
        key=lambda w: w.x0,
    )
    if not headers or headers[0].text != "條件":
        raise ValueError("表4 表頭判讀失敗：%s" % [w.text for w in headers])

    benchmark = _cell_range(edges, headers[0])
    pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    rest = headers[1:]
    for i in range(0, len(rest) - 1, 2):
        cond, diff = rest[i], rest[i + 1]
        if (cond.text, diff.text) != ("條件", "差異率"):
            raise ValueError("表4 表頭欄序異常：%s / %s" % (cond.text, diff.text))
        pairs.append((_cell_range(edges, cond), _cell_range(edges, diff)))
    return Columns(benchmark=benchmark, comparables=tuple(pairs))


# ---------- 值解析 ----------

_NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


def _to_number(text: str) -> float | int:
    n = float(text.replace(",", ""))
    return int(n) if n == int(n) else n


def parse_value(kind: str, words: list[Word]) -> tuple[Any, str | None]:
    """把一格的 word 們解成 (值, 顯示標籤)。空格回傳 (None, None)。

    標籤只有「名稱＋距離」型才有：golden JSON 的 `fact_labels` 就是存
    「中山路 18M」這種原始寫法，讓報告能照原文呈現而不是只給數字。
    """
    if not words:
        return (None, None)
    texts = [w.text for w in words]

    if kind == NUM:
        return (_to_number(texts[0]), None)
    if kind == PCT:
        return (_to_number(texts[0].rstrip("%")), None)
    if kind == TEXT:
        # 中文欄位不含空白，直接相接；用空白接會產生「第二種 商業區」這種假值。
        return ("".join(texts), None)
    if kind == NAMED_DIST:
        return _parse_named_distance(texts)
    raise ValueError("未知的欄位型別 %r" % kind)


_TRAILING_DISTANCE_RE = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s*M?\s*$", re.IGNORECASE)


def _parse_named_distance(texts: list[str]) -> tuple[Any, str]:
    """`中山路 18 M` → (18, "中山路 18M")。

    距離是末尾的數字，名稱是它前面的部分。不能靠「哪一個 word 剛好是純數字」
    來找——那取決於產生 PDF 的軟體怎麼排字：官方範本把它排成三個 word
    （`中山路` `18` `M`），我們自己重繪的同一格卻是 `中山路` `18M` 兩個。
    所以先接成一串再從尾端取數字，兩種寫法都吃得下。

    也不假設一定有單位「M」，因為同一欄在不同案件可能只填數字。
    """
    joined = "".join(texts)
    m = _TRAILING_DISTANCE_RE.search(joined)
    if m is None:
        raise ValueError("名稱＋距離欄找不到數字：%r" % texts)
    value = _to_number(m.group(1))
    name = joined[: m.start()].strip()
    return (value, "%s %sM" % (name, m.group(1)) if name else "%sM" % m.group(1))


# ---------- 主流程 ----------


def parse(page: Page) -> Table4:
    cols = locate_columns(page)
    words = page.words
    prov = Provenance()

    def row_y(label: str) -> float:
        return find_label(words, label, (0, LABEL_X_MAX)).y_center

    def cell(x_range: tuple[float, float], y: float) -> list[Word]:
        return words_at(words, x_range, y)

    def take(path: str, x_range: tuple[float, float], y: float, kind: str) -> tuple[Any, str | None]:
        got = cell(x_range, y)
        value, label = parse_value(kind, got)
        if got:
            prov.record(
                path,
                FieldSource(page.number, bbox_of(got), " ".join(w.text for w in got)),
            )
        return (value, label)

    case_id = _header_field(words, "案號：")
    base_date = _header_field(words, "估價基準日：")

    y0 = row_y("0基本資料")
    y_segment = row_y("地價區段")
    benchmark: dict[str, Any] = {
        "label": "比準地",
        "parcel": take("benchmark.parcel", cols.benchmark, y0, TEXT)[0],
        "segment": take("benchmark.segment", cols.benchmark, y_segment, TEXT)[0],
        "facts": {},
        "fact_labels": {},
    }

    comparables: list[dict[str, Any]] = []
    for i, (cond, diff) in enumerate(cols.comparables, start=1):
        if not cell(cond, y0):
            continue  # 版面固定留 3 件，未填的直接跳過
        comparables.append(
            _parse_comparable(i, cond, diff, y0, y_segment, take, cell, words, row_y, prov, page.number)
        )

    for label, factor_id, kind in FACTOR_ROWS:
        y = row_y(label)
        value, text_label = take("benchmark.facts.%s" % factor_id, cols.benchmark, y, kind)
        benchmark["facts"][factor_id] = value
        if text_label:
            benchmark["fact_labels"][factor_id] = text_label

        for c, (cond, diff) in zip(comparables, cols.comparables):
            idx = c["index"]
            value, text_label = take(
                "comparables[%d].facts.%s" % (idx, factor_id), cond, y, kind
            )
            c["facts"][factor_id] = value
            if text_label:
                c["fact_labels"][factor_id] = text_label
            filed = take(
                "comparables[%d].filed_corrections.%s" % (idx, factor_id), diff, y, PCT
            )[0]
            if filed is not None:
                c["filed_corrections"][factor_id] = filed

    # 比準地比較價格是整張表的結論，印在一個橫跨多欄的合併儲存格裡，
    # 不屬於任何一個比較標的，所以單獨處理。
    y_bcp = row_y("比準地比較價格")
    bcp_words = [
        w
        for w in words
        if w.x0 > LABEL_X_MAX and abs(w.y_center - y_bcp) <= 5.0 and _NUM_RE.match(w.text)
    ]
    benchmark_comparison_price = _to_number(bcp_words[0].text) if bcp_words else None
    if bcp_words:
        prov.record(
            "benchmark_comparison_price",
            FieldSource(page.number, bbox_of(bcp_words), bcp_words[0].text),
        )

    return Table4(
        case_id=case_id,
        appraisal_base_date=base_date,
        benchmark=benchmark,
        comparables=comparables,
        benchmark_comparison_price=benchmark_comparison_price,
        provenance=prov,
    )


def _parse_comparable(i, cond, diff, y0, y_segment, take, cell, words, row_y, prov, page_no) -> dict[str, Any]:
    """一個比較標的的基本資料與價格欄。個別因素各列在主流程統一填。"""
    y_price = row_y("土地正常單價")
    y_date = row_y("交易日期")
    y_display = row_y("調整至估價基準日單價(元/M2)")

    comparable: dict[str, Any] = {
        "index": i,
        "example_no": _example_no(words, cond, diff),
        "parcel": take("comparables[%d].parcel" % i, cond, y0, TEXT)[0],
        "segment": take("comparables[%d].segment" % i, cond, y_segment, TEXT)[0],
        "transaction_date": take("comparables[%d].transaction_date" % i, cond, y_date, TEXT)[0],
        "normal_unit_price": take("comparables[%d].normal_unit_price" % i, cond, y_price, NUM)[0],
        "date_adjustment_pct": take("comparables[%d].date_adjustment_pct" % i, diff, y_date, PCT)[0],
        "date_adjusted_unit_price_displayed": take(
            "comparables[%d].date_adjusted_unit_price_displayed" % i, cond, y_display, NUM
        )[0],
        "regional_adjustment_pct": take(
            "comparables[%d].regional_adjustment_pct" % i, diff, y_segment, PCT
        )[0],
        "facts": {},
        "fact_labels": {},
        "filed_corrections": {},
    }

    # 合計／絕對值加總／試算價格／權重都印在「條件」欄內，同一列裡混著
    # 百分比與金額，所以按「有沒有 %」分辨，不按 x 位置——那幾列的
    # 排版與個別因素各列不同，用座標會寫死三個特例。
    def summary(label: str, path: str, pick: str) -> Any:
        got = cell(cond, row_y(label))
        value = _numbers_in(got)[pick] if pick != "text" else _non_numeric(got)
        target = [
            w
            for w in got
            if (pick == "text") == (not _NUM_RE.match(w.text.rstrip("%")))
        ]
        if target:
            prov.record(
                "comparables[%d].%s" % (i, path),
                FieldSource(page_no, bbox_of(target), " ".join(w.text for w in target)),
            )
        return value

    comparable["individual_total_pct"] = summary("合計", "individual_total_pct", "percent")
    comparable["abs_sum_pct"] = summary("調整百分率絕對值加總", "abs_sum_pct", "percent")
    comparable["similarity_label"] = summary("調整百分率絕對值加總", "similarity_label", "text")
    comparable["trial_price"] = summary("試算價格", "trial_price", "plain")
    comparable["weight_pct"] = summary("試算價格", "weight_pct", "percent")

    return comparable


def _numbers_in(words: Iterable[Word]) -> dict[str, Any]:
    """一格裡的數字，分成帶 % 與不帶 % 兩種。"""
    percent = plain = None
    for w in words:
        t = w.text
        if t.endswith("%") and _NUM_RE.match(t[:-1]):
            percent = _to_number(t[:-1])
        elif _NUM_RE.match(t):
            plain = _to_number(t)
    return {"percent": percent, "plain": plain}


def _non_numeric(words: Iterable[Word]) -> str | None:
    hits = [w.text for w in words if not _NUM_RE.match(w.text.rstrip("%"))]
    return "".join(hits) or None


def _example_no(words, cond: tuple[float, float], diff: tuple[float, float]) -> str | None:
    """表頭「比較標的1 實例編號： 1」的編號。

    編號印在差異率欄的位置（範本實測 x=455 落在 443–470），
    但它不是差異率，所以單獨處理而不是走欄位對照表。
    """
    band = (cond[0], diff[1])
    head = [w for w in words if band[0] <= w.x0 < band[1] and w.top < 55]
    for i, w in enumerate(head):
        if w.text.startswith("實例編號") and i + 1 < len(head):
            return head[i + 1].text
    return None


def _header_field(words, prefix: str) -> str:
    for w in words:
        if w.text.startswith(prefix):
            return w.text[len(prefix):]
    raise LookupError("表頭找不到 %r" % prefix)
