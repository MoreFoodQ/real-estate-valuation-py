"""表5-2 影響地價區域因素分析明細表 辨識器。

這張表走 cell 網格而不是座標，因為細項名會折成 2–3 行，而等級值落在
折行區塊的**中間**那一行（範本實測：「有無限制建築（整體開發、面／積限制、
高度限制……等）」標籤在 y=183.8 與 193.7，等級卻在 y=188.2）。
用座標得先還原折行分組，用網格則 pdfplumber 已經把整格文字併好。

注意這張表在範本裡**一條 line 都沒有**，框線全是 rect 畫的；
`extract.py` 兩種都收，所以網格切得出來。

本檔的 `FACTOR_ROWS` 是「書表細項名 → factor_id」的正本。kernel 的區域因素
規則集目前只有 5/28 項，日後補完 23 項時必須沿用這裡的 id，否則辨識層與
引擎層會對不起來（已存在的 5 個 id 就是照 kernel 現況寫的）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .extract import BBox, Grid, GridBoxes, Page
from .provenance import FieldSource, Provenance

# 表5-2 的 13 欄：0 主要項目、1 修正細項、2-3 比準地等級（數字, 文字）、
# 之後每個比較標的佔 3 欄（等級數字, 等級文字, 修正百分比）。
COL_GROUP = 0
COL_FACTOR = 1
COL_BENCHMARK_GRADE = 2
COL_BENCHMARK_LABEL = 3
COMPARABLE_COL_START = 4
COMPARABLE_COL_STRIDE = 3

# 主要項目的標籤都是「土地使用管制(1)」這種形狀，末尾帶組別序號。
_GROUP_RE = re.compile(r"\([1-8]\)$")

SUBTOTAL_LABEL = "百分比小計"
TOTAL_PREFIX = "=(1)"
HEADER_LABEL = "主要項目"
SEGMENT_LABEL = "地價區段號"
REMARK_LABEL = "備註欄"

# 五級制的等級文字。二級制（有無禁建、有無限建）在書表上印的是「無／有」，
# 不是「優／劣」，所以另外一組——只用五級那組去檢核會誤報。
GRADE_LABELS: dict[str, int] = {"優": 1, "稍優": 2, "普通": 3, "稍劣": 4, "劣": 5}
BINARY_LABELS: dict[str, int] = {"無": 1, "有": 2}

# 28 個修正細項 → factor_id。順序即書表順序，不要重排。
FACTOR_ROWS: tuple[tuple[str, str], ...] = (
    ("都市計畫（內、外）", "regional.land_control.urban_plan"),
    ("使用分區(使用地類別)", "regional.land_control.zoning"),
    ("建蔽率", "regional.land_control.building_coverage"),
    ("容積率", "regional.land_control.floor_area_ratio"),
    ("有無禁止建築", "regional.land_control.build_prohibition"),
    ("有無限制建築（整體開發、面積限制、高度限制……等）", "regional.land_control.build_restriction"),
    ("主要道路寬度", "regional.transport.main_road_width"),
    ("區段內道路平均寬度", "regional.transport.avg_road_width"),
    ("接近大型車站之程度", "regional.transport.large_station"),
    ("站牌之接近程度或密集程度", "regional.transport.bus_stop"),
    ("交流道之有無及接近交流道之程度", "regional.transport.interchange"),
    ("區段內道路規劃及闢建程度", "regional.transport.road_development"),
    ("排水之良否", "regional.nature.drainage"),
    ("地勢", "regional.nature.terrain"),
    ("接近市場之程度（傳統市場、超級市場、超大型購物中心）", "regional.public.market"),
    ("接近公園（里鄰公園、一般公園）、廣場、徒步區之程度", "regional.public.park"),
    ("接近觀光遊憩設施之程度", "regional.public.tourism"),
    ("停車場地之便利程度", "regional.public.parking"),
    ("電業設施及公用氣體燃料設施之有無及接近程度", "regional.special.utility"),
    ("殯葬設施之有無及接近程度", "regional.special.funeral"),
    ("廢棄物處理設施之有無及接近程度", "regional.special.waste"),
    ("水污染、噪音污染、廢氣污染、廢棄物污染等之有無及接近程度", "regional.pollution.environmental"),
    ("百貨公司之有無、數量、接近程度", "regional.commerce.department_store"),
    ("金融機構之有無、數量、接近程度", "regional.commerce.financial"),
    ("娛樂設施之有無、數量、接近程度", "regional.commerce.entertainment"),
    ("大型展示中心或觀光飯店之有無、數量、接近程度", "regional.commerce.exhibition_hotel"),
    ("顧客通行量之多寡", "regional.commerce.customer_traffic"),
    ("店舖之毗連狀態", "regional.commerce.shop_continuity"),
)

_BY_NAME: dict[str, str] = {name: fid for name, fid in FACTOR_ROWS}
# factor_id → 書表上的中文細項名。UI 要顯示它，這份對照表在後端，
# 前端不該自己再抄一份——抄了就會有兩份會不同步的真相。
FACTOR_LABELS: dict[str, str] = {fid: name for name, fid in FACTOR_ROWS}


@dataclass
class Table5_2:
    case_id: str
    land_use: str
    benchmark_segment: str | None
    benchmark_grades: dict[str, dict[str, Any]]
    comparables: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    warnings: list[dict[str, str]] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "land_use": self.land_use,
            "benchmark_segment": self.benchmark_segment,
            "benchmark_grades": self.benchmark_grades,
            "comparables": self.comparables,
            "groups": self.groups,
            "factor_labels": FACTOR_LABELS,
            "warnings": self.warnings,
        }


def _clean(cell: str | None) -> str:
    """去掉折行與空白。書表的細項名是排版折的，不是內容的一部分。"""
    if not cell:
        return ""
    return "".join(cell.split())


def parse(page: Page) -> Table5_2:
    grid = page.main_grid()
    boxes = page.main_grid_boxes()
    rows = [tuple(_clean(c) for c in row) for row in grid]

    header_idx = _row_index(rows, COL_GROUP, HEADER_LABEL)
    n_comparables = _count_comparables(rows, header_idx)

    result = Table5_2(
        case_id=_case_id(rows),
        land_use=_land_use(page),
        benchmark_segment=None,
        benchmark_grades={},
        comparables=[
            {
                "index": i + 1,
                "example_no": _example_no(rows, i),
                "segment": None,
                "grades": {},
                "filed_corrections": {},
                "filed_subtotals": {},
                "filed_total": None,
            }
            for i in range(n_comparables)
        ],
        groups=[],
    )

    _read_segments(rows, result)
    _read_body(rows, boxes, header_idx, result, page.number)
    return result


def _union(*boxes: BBox | None) -> BBox | None:
    """把相鄰儲存格的 bbox 併起來。等級欄是「數字」「文字」兩格，
    但它在書表上是一個欄位，填值時要當成一格處理。"""
    got = [b for b in boxes if b is not None]
    if not got:
        return None
    return (
        min(b[0] for b in got),
        min(b[1] for b in got),
        max(b[2] for b in got),
        max(b[3] for b in got),
    )


# ---------- 表頭 ----------


def _row_index(rows: list[tuple[str, ...]], col: int, text: str) -> int:
    for i, row in enumerate(rows):
        if col < len(row) and row[col] == text:
            return i
    raise LookupError("表5-2 找不到 %r 這一列" % text)


def _case_id(rows: list[tuple[str, ...]]) -> str:
    for row in rows[:3]:
        for cell in row:
            if cell.startswith("案號："):
                return cell[len("案號："):]
    raise LookupError("表5-2 表頭找不到案號")


def _land_use(page: Page) -> str:
    """從標題「影響地價區域因素分析明細表（商業用地）」取用地別。

    用地別決定該用哪一式的評價基準表（內政部附件24 分住宅／商業／工業／
    農業／其他 5 式），所以必須抽出來，不能假設是商業用地。
    """
    for w in page.words:
        if "影響地價區域因素分析明細表" in w.text and "（" in w.text:
            return w.text.split("（")[1].rstrip("）")
    raise LookupError("表5-2 標題裡找不到用地別")


def _count_comparables(rows: list[tuple[str, ...]], header_idx: int) -> int:
    """依「哪幾個比較標的的等級欄真的有值」決定數量。

    書表版面固定留 3 件，範本只填 1 件，空欄不能被當成資料。
    """
    count = 0
    for i in range(3):
        col = COMPARABLE_COL_START + i * COMPARABLE_COL_STRIDE
        if any(
            col < len(row) and row[col]
            for row in rows[header_idx + 1:]
        ):
            count = i + 1
    return count


def _example_no(rows: list[tuple[str, ...]], i: int) -> str | None:
    """表頭的「實例編號 1」。未填的比較標的只有「實例編號」四個字。"""
    col = COMPARABLE_COL_START + i * COMPARABLE_COL_STRIDE + 1
    for row in rows[:2]:
        if col < len(row) and row[col].startswith("實例編號"):
            no = row[col][len("實例編號"):]
            return no or None
    return None


def _read_segments(rows: list[tuple[str, ...]], result: Table5_2) -> None:
    idx = _row_index(rows, COL_GROUP, SEGMENT_LABEL)
    row = rows[idx]
    result.benchmark_segment = row[COL_BENCHMARK_GRADE] or None
    for i, c in enumerate(result.comparables):
        col = COMPARABLE_COL_START + i * COMPARABLE_COL_STRIDE
        c["segment"] = (row[col] if col < len(row) else "") or None


# ---------- 表身 ----------


def _read_body(
    rows: list[tuple[str, ...]],
    boxes: GridBoxes,
    header_idx: int,
    result: Table5_2,
    page_no: int,
) -> None:
    current: dict[str, Any] | None = None
    pending = ""

    for ridx in range(header_idx + 1, len(rows)):
        row = rows[ridx]
        group_cell = row[COL_GROUP]
        name = row[COL_FACTOR]

        if group_cell == REMARK_LABEL:
            break

        # 群組標籤一律以 (1)…(8) 結尾。不能直接把 col0 當群組：
        # 範本裡「其他影響／因素(8)」被切成兩個網格列，而總修正數列的 col0
        # 是「影響地價區域因素總修正數」——照收會多出三個不存在的群組。
        if group_cell:
            pending += group_cell
            if _GROUP_RE.search(pending):
                current = {"label": pending, "factor_ids": []}
                result.groups.append(current)
                pending = ""

        if not name:
            continue
        if name == SUBTOTAL_LABEL:
            _read_percent_row(row, boxes[ridx] if ridx < len(boxes) else (),
                              result, current, page_no, is_total=False)
            continue
        if name.startswith(TOTAL_PREFIX):
            _read_percent_row(row, boxes[ridx] if ridx < len(boxes) else (),
                              result, current, page_no, is_total=True)
            continue

        factor_id = _BY_NAME.get(name)
        if factor_id is None:
            result.warnings.append(
                {
                    "code": "unknown_factor_row",
                    "message": "表5-2 出現對照表沒有的細項：%s" % name,
                    "path": "",
                }
            )
            continue
        if current is not None:
            current["factor_ids"].append(factor_id)
        _read_factor_row(row, boxes[ridx] if ridx < len(boxes) else (), factor_id, result, page_no)


def _read_factor_row(
    row: tuple[str, ...],
    row_boxes: tuple[BBox | None, ...],
    factor_id: str,
    result: Table5_2,
    page_no: int,
) -> None:
    def box(*cols: int) -> BBox | None:
        return _union(*(row_boxes[c] for c in cols if c < len(row_boxes)))

    result.benchmark_grades[factor_id] = _grade_cell(
        row[COL_BENCHMARK_GRADE], row[COL_BENCHMARK_LABEL], factor_id, "比準地", result
    )
    # 等級欄在書表上是「數字」「文字」兩格，各自記一筆——併成一格會讓填出來的
    # 字落在格線上。
    for col, name in ((COL_BENCHMARK_GRADE, "grade"), (COL_BENCHMARK_LABEL, "label")):
        result.provenance.record(
            "benchmark_grades.%s.%s" % (factor_id, name),
            FieldSource(page_no, box(col), row[col]),
        )

    for i, c in enumerate(result.comparables):
        base = COMPARABLE_COL_START + i * COMPARABLE_COL_STRIDE
        if base + 2 >= len(row):
            continue
        c["grades"][factor_id] = _grade_cell(
            row[base], row[base + 1], factor_id, "比較標的%d" % (i + 1), result
        )
        pct = _to_pct(row[base + 2])
        if pct is not None:
            c["filed_corrections"][factor_id] = pct
        for col, name in ((base, "grade"), (base + 1, "label")):
            result.provenance.record(
                "comparables[%d].grades.%s.%s" % (i + 1, factor_id, name),
                FieldSource(page_no, box(col), row[col]),
            )
        result.provenance.record(
            "comparables[%d].filed_corrections.%s" % (i + 1, factor_id),
            FieldSource(page_no, box(base + 2), row[base + 2]),
        )


def _grade_cell(
    number: str, label: str, factor_id: str, side: str, result: Table5_2
) -> dict[str, Any]:
    """等級欄同時有數字與文字，兩者必須一致。

    不一致就發警告——這本身就是一個檢核項（手冊審查重點第 vi 項要求
    「修正細項優劣等級與各該地價區段勘查表所載內容一致」，
    表內數字與文字自相矛盾時，抄寫錯誤已經發生了）。
    """
    grade = int(number) if number.isdigit() else None
    expected = GRADE_LABELS.get(label, BINARY_LABELS.get(label))

    if grade is None:
        result.warnings.append(
            {
                "code": "grade_not_a_number",
                "message": "%s 的「%s」等級欄不是數字：%r" % (side, factor_id, number),
                "path": factor_id,
            }
        )
    elif expected is None:
        result.warnings.append(
            {
                "code": "unknown_grade_label",
                "message": "%s 的「%s」等級文字不在已知集合：%r" % (side, factor_id, label),
                "path": factor_id,
            }
        )
    elif expected != grade:
        result.warnings.append(
            {
                "code": "grade_label_mismatch",
                "message": "%s 的「%s」等級數字 %d 與文字「%s」（應為 %d）不符"
                % (side, factor_id, grade, label, expected),
                "path": factor_id,
            }
        )
    return {"grade": grade, "label": label}


def _read_percent_row(
    row: tuple[str, ...],
    row_boxes: tuple[BBox | None, ...],
    result: Table5_2,
    group: dict[str, Any] | None,
    page_no: int,
    is_total: bool,
) -> None:
    """小計／總修正數列。

    這兩種列的百分比是印在合併儲存格裡的，落點與資料列的修正百分比欄不同
    （範本實測落在比較標的1 的等級文字欄）。所以不按欄位取，
    而是取整列裡帶「％」的儲存格，依序對應各比較標的。
    """
    cells = [
        (i, cell)
        for i, cell in enumerate(row)
        if i >= COL_BENCHMARK_GRADE and "％" in cell
    ]
    for c, (col, cell) in zip(result.comparables, cells):
        value = _to_pct(cell.rstrip("％"))
        box = row_boxes[col] if col < len(row_boxes) else None
        if is_total:
            c["filed_total"] = value
            path = "comparables[%d].filed_total" % c["index"]
        elif group is not None:
            c["filed_subtotals"][group["label"]] = value
            path = "comparables[%d].filed_subtotals.%s" % (c["index"], group["label"])
        else:
            continue
        result.provenance.record(path, FieldSource(page_no, box, cell))


def _to_pct(text: str) -> float | int | None:
    t = text.replace("％", "").replace("%", "").strip()
    if not t:
        return None
    try:
        n = float(t)
    except ValueError:
        return None
    return int(n) if n == int(n) else n
