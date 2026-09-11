"""表1 地價區段勘查表 辨識器。

這張表是三張裡最難的：40 餘個欄位、左右兩個面板並排、大量 ○／● 圈選、
名稱＋距離組合欄，而且每個細項左側印著「等級 級數」兩個數字。

三個實測到的陷阱，都寫成了程式裡的規則：

1. **等級可能落在標籤的下一列。** 儲存格跨列時文字畫在垂直置中處，
   pdfplumber 會把它切到下一個網格列——「市場」標籤在 r31、等級 `1 5` 在 r32；
   「廢棄物處理」標籤在 r18、等級在 r19。所以找等級要往下一列、再往上一列找。

2. **同一列左右各有一組等級。** r14 左邊是交流道 5/5、右邊是殯葬 5/5。
   取值必須分面板，不能整列掃。

3. **級數不一定是 5。** 都市計畫內外、有無禁止建築、有無限制建築都是 2 級。
   把 5 寫死會讓這三項的等級語意整個錯掉，所以級數要一起抽出來。

本檔只負責「表1 寫了什麼」。「寫得對不對」（量測值與等級是否相符）是
審查模式的事，屬於 kernel，不在辨識層做——辨識層一旦開始判斷對錯，
就沒有東西能當作被審查的原始輸入了。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .extract import BBox, Grid, GridBoxes, Page
from .provenance import FieldSource, Provenance

LEFT = "left"
RIGHT = "right"

# 左面板：0 群組、1 等級、2 級數、3 細項名、4-8 值。
# 右面板：9 群組、10 等級、11 級數、12 細項名、13-15 值。
PANELS: dict[str, dict[str, Any]] = {
    LEFT: {"grade": (1, 2), "labels": (3,), "values": range(4, 9)},
    RIGHT: {"grade": (10, 11), "labels": (12, 9), "values": range(13, 16)},
}

# 表1 的細項名 → factor_id。名稱用書表上的寫法（去空白後前綴比對），
# 與表5-2 的細項名不同（表1「主要道路」＝表5-2「主要道路寬度」），
# 所以兩張表各有一份對照表，不能共用。
TABLE1_ROWS: tuple[tuple[str, str, str], ...] = (
    ("都市計畫(內外)", LEFT, "regional.land_control.urban_plan"),
    ("使用分區(使用地類別)", LEFT, "regional.land_control.zoning"),
    ("建蔽率", LEFT, "regional.land_control.building_coverage"),
    ("容積率", LEFT, "regional.land_control.floor_area_ratio"),
    ("有無禁止建築", LEFT, "regional.land_control.build_prohibition"),
    ("有無限制建築", LEFT, "regional.land_control.build_restriction"),
    ("主要道路", LEFT, "regional.transport.main_road_width"),
    ("區段內道路平均寬度", LEFT, "regional.transport.avg_road_width"),
    ("大型車站", LEFT, "regional.transport.large_station"),
    ("站牌", LEFT, "regional.transport.bus_stop"),
    ("交流道", LEFT, "regional.transport.interchange"),
    ("區段內道路規劃及闢建程度", LEFT, "regional.transport.road_development"),
    ("保（排）水之良否", LEFT, "regional.nature.drainage"),
    ("地勢", LEFT, "regional.nature.terrain"),
    ("市場", LEFT, "regional.public.market"),
    ("公園", LEFT, "regional.public.park"),
    ("觀光遊憩設施", RIGHT, "regional.public.tourism"),
    ("停車場地", RIGHT, "regional.public.parking"),
    ("電業", RIGHT, "regional.special.utility"),
    ("殯葬", RIGHT, "regional.special.funeral"),
    ("廢棄物處理", RIGHT, "regional.special.waste"),
    ("環境污染", RIGHT, "regional.pollution.environmental"),
    ("百貨公司", RIGHT, "regional.commerce.department_store"),
    ("金融機構", RIGHT, "regional.commerce.financial"),
    ("娛樂設施", RIGHT, "regional.commerce.entertainment"),
    ("大型展示中心", RIGHT, "regional.commerce.exhibition_hotel"),
    ("顧客之通行量", RIGHT, "regional.commerce.customer_traffic"),
    ("店鋪之毗連狀態", RIGHT, "regional.commerce.shop_continuity"),
)

_SELECTED_RE = re.compile(r"●([^○●\n]*)")
_DISTANCE_RE = re.compile(r"距\s*([\d,.]+)\s*M", re.IGNORECASE)
_NAME_RE = re.compile(r"名稱：([^○●\n]*?)(?:數量[:：]|(?=[○●])|$)")
_QUANTITY_RE = re.compile(r"數量[:：]\s*(\d+)")
_NUMBER_UNIT_RE = re.compile(r"([\d,.]+)\s*(%|M)", re.IGNORECASE)

# 「本區段內」「本區段外(距 300 M)」是位置標記，不是選項。
_LOCATION_PREFIXES = ("本區段內", "本區段外")


@dataclass
class Table1:
    period: str | None
    segment_no: str | None
    segment_scope: str | None
    grades: dict[str, dict[str, Any]]
    surveys: dict[str, dict[str, Any]]
    warnings: list[dict[str, str]] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "segment_no": self.segment_no,
            "segment_scope": self.segment_scope,
            "grades": self.grades,
            "surveys": self.surveys,
            "warnings": self.warnings,
        }


def _cell(boxes: GridBoxes, row: int, col: int) -> BBox | None:
    if not 0 <= row < len(boxes) or col >= len(boxes[row]):
        return None
    return boxes[row][col]


def _union(*boxes: BBox | None) -> BBox | None:
    got = [b for b in boxes if b is not None]
    if not got:
        return None
    return (
        min(b[0] for b in got),
        min(b[1] for b in got),
        max(b[2] for b in got),
        max(b[3] for b in got),
    )


def _clean(cell: str | None) -> str:
    """去掉排版用的空白，但**保留換行**——換行是多筆子項目的分隔。

    例如殯葬欄的四列（墓地／殯儀館／火葬場／納骨塔）就是靠換行分開的，
    全部併成一行會讓「哪一個被圈選、距離多少」對不起來。
    """
    if not cell:
        return ""
    return "\n".join("".join(line.split()) for line in cell.split("\n"))


def _flat(cell: str) -> str:
    """連換行一起拿掉，只用於比對標籤。

    表1 有五個細項是直排的（`大型車⏎站`、`電⏎業⏎氣⏎體⏎燃⏎料`、`殯⏎葬`、
    `廢⏎棄⏎物⏎處⏎理`、`環⏎境⏎污⏎染`），保留換行的版本比對不到。
    但取值時不能用這個版本——那會把多筆子項目黏成一團。
    """
    return "".join(cell.split())


def parse(page: Page) -> Table1:
    grid: Grid = page.main_grid()
    boxes: GridBoxes = page.main_grid_boxes()
    rows = [tuple(_clean(c) for c in row) for row in grid]

    result = Table1(
        period=_header_cell(rows, "年期"),
        segment_no=_header_cell(rows, "區段編號"),
        segment_scope=_header_cell(rows, "區段範圍", contains=True),
        grades={},
        surveys={},
    )

    for alias, panel, factor_id in TABLE1_ROWS:
        idx = _find_label_row(rows, alias, panel)
        if idx is None:
            result.warnings.append(
                {
                    "code": "factor_row_not_found",
                    "message": "表1 找不到細項「%s」" % alias,
                    "path": factor_id,
                }
            )
            continue

        grade, count = _find_grade(rows, idx, panel, result, alias, factor_id)
        result.grades[factor_id] = {"grade": grade, "grade_count": count, "label_in_form": alias}

        raw, rows_used = _value_text(rows, idx, panel, alias)
        result.surveys[factor_id] = parse_survey_cell(raw)
        # 等級與級數在書表上是相鄰的兩格，各自記一筆——併成一個 bbox 的話，
        # 填出來的字會落在兩格中間的格線上。
        gcol, ccol = PANELS[panel]["grade"]
        grade_row = _grade_row(rows, idx, panel)
        for col, value, name in ((gcol, grade, "grade"), (ccol, count, "grade_count")):
            result.provenance.record(
                "grades.%s.%s" % (factor_id, name),
                FieldSource(page.number, _cell(boxes, grade_row, col), "" if value is None else str(value)),
            )
        result.provenance.record(
            "surveys.%s" % factor_id,
            FieldSource(
                page.number,
                # bbox 必須涵蓋所有被讀進來的列，包含延續列。只涵蓋第一列的話，
                # 延續列的字會留在靜態層，產表時就會與填進去的值疊在一起
                # （電業設施的變電所／瓦斯槽是分兩列畫的，實測會重複顯示）。
                _union(*(_cell(boxes, r, c) for r in rows_used for c in PANELS[panel]["values"])),
                raw,
            ),
        )

    return result


# ---------- 表頭 ----------


def _header_cell(rows: list[tuple[str, ...]], label: str, contains: bool = False) -> str | None:
    """表頭是「標籤在左、值在右邊第一個非空格」的形狀。"""
    for row in rows[:2]:
        for i, cell in enumerate(row):
            flat = _flat(cell)
            hit = label in flat if contains else flat == label
            if hit:
                for nxt in row[i + 1:]:
                    if nxt:
                        return nxt
    return None


# ---------- 定位 ----------


def _find_label_row(rows: list[tuple[str, ...]], alias: str, panel: str) -> int | None:
    """用前綴比對找細項所在列。

    必須限定在該面板的標籤欄比對，不能整列找：「市場」在同一列的值欄裡
    以「金山區第一零售傳統市場」出現過，整列比對會命中錯的格子。
    前綴而非完全相符，是因為有些格子把值併在標籤後面
    （「區段內道路平均寬度 12 M」）。
    """
    for idx, row in enumerate(rows):
        for col in PANELS[panel]["labels"]:
            if col < len(row) and _flat(row[col]).startswith(alias):
                return idx
    return None


def _grade_row(rows: list[tuple[str, ...]], idx: int, panel: str) -> int:
    """等級實際落在哪一列。跨列儲存格會把它切到相鄰列，見 `_find_grade`。"""
    gcol, ccol = PANELS[panel]["grade"]
    for offset in (0, 1, -1):
        i = idx + offset
        if 0 <= i < len(rows) and max(gcol, ccol) < len(rows[i]):
            if rows[i][gcol].isdigit() and rows[i][ccol].isdigit():
                return i
    return idx


def _find_grade(
    rows: list[tuple[str, ...]],
    idx: int,
    panel: str,
    result: Table1,
    alias: str,
    factor_id: str,
) -> tuple[int | None, int | None]:
    """在同列找等級／級數，找不到就往下一列、再往上一列。

    跨列儲存格的文字畫在垂直置中處，會被切到相鄰的網格列
    （「市場」標籤 r31、等級在 r32；「廢棄物處理」標籤 r18、等級在 r19）。
    """
    gcol, ccol = PANELS[panel]["grade"]
    for offset in (0, 1, -1):
        i = idx + offset
        if not 0 <= i < len(rows):
            continue
        row = rows[i]
        if max(gcol, ccol) >= len(row):
            continue
        g, c = row[gcol], row[ccol]
        if g.isdigit() and c.isdigit():
            return int(g), int(c)

    result.warnings.append(
        {
            "code": "grade_not_found",
            "message": "表1 細項「%s」附近找不到等級／級數" % alias,
            "path": factor_id,
        }
    )
    return (None, None)


def _value_text(
    rows: list[tuple[str, ...]], idx: int, panel: str, alias: str
) -> tuple[str, list[int]]:
    """細項的值：標籤右側各欄，加上後續的延續列。

    延續列指「同面板、標籤欄空著但值欄有內容」的列——電業設施的
    變電所（r11）與瓦斯槽（r12）就是分成兩列畫的，只讀第一列會漏掉
    第二個設施，而這一項的規則是**多設施取最劣**，漏一個就可能取錯。
    """
    parts: list[str] = []
    used: list[int] = [idx]
    label_cols = PANELS[panel]["labels"]
    value_cols = PANELS[panel]["values"]

    head = rows[idx]
    # 值有時被併在標籤格裡（「區段內道路平均寬度 12 M」），把標籤本身切掉留下值。
    # 但只在剩下的部分含數字時才採用——否則會把折行的標籤尾巴當成值
    # （「公園／廣場／徒步區」的後兩行、「大型展示中心或觀光飯店」的後半）。
    for col in label_cols:
        if col < len(head) and _flat(head[col]).startswith(alias):
            tail = _flat(head[col])[len(alias):]
            if any(ch.isdigit() for ch in tail):
                parts.append(tail)
            break
    parts.append(_join_cells([head[c] for c in value_cols if c < len(head) and head[c]]))

    for offset, row in enumerate(rows[idx + 1:], start=idx + 1):
        has_label = any(c < len(row) and row[c] for c in label_cols)
        values = [row[c] for c in value_cols if c < len(row) and row[c]]
        if has_label or not values:
            break
        parts.append(_join_cells(values))
        used.append(offset)

    return "\n".join(p for p in parts if p), used


def _join_cells(cells: list[str]) -> str:
    """同一列的多個值欄，行數相同時逐行對齊合併。

    殯葬欄的選項在一格（●墓地／○殯儀館／○火葬場／●納骨塔），名稱與距離
    在另一格（名稱：金山第1公墓…80M／名稱：無／…），兩格行數相同、位置對應。
    直接前後串接會讓「哪個設施距離多遠」失去配對，而這一項的規則是
    **多設施取最劣**（手冊 p.24），配對錯了就可能取錯那一個。
    """
    if len(cells) > 1:
        counts = {c.count("\n") for c in cells}
        if len(counts) == 1 and counts.pop() > 0:
            return "\n".join(
                " ".join(parts) for parts in zip(*(c.split("\n") for c in cells))
            )
    return "\n".join(cells)


# ---------- 值解析 ----------


def parse_survey_cell(raw: str) -> dict[str, Any]:
    """把勘查表的一格解成結構化資料。

    刻意同時保留 `raw`：這張表的欄位型態太雜（圈選、名稱＋距離、純文字、
    百分比、複選），任何結構化都可能漏掉某種寫法。原文留著，
    UI 就永遠能顯示估價師實際寫了什麼，審查也永遠有原始依據可看。
    """
    entries: list[dict[str, Any]] = []
    for line in raw.split("\n"):
        if "●" not in line and "名稱：" not in line:
            continue

        # 「●本區段內」「●本區段外」是位置標記，不是選項本身。
        # 不分開處理的話，「●金山區第一零售傳統市場 ●本區段內」會被算成兩個選項。
        marks = [m.strip() for m in _SELECTED_RE.findall(line)]
        # 逐行對齊合併後，選項與名稱會落在同一行（「●墓地 名稱：金山第1公墓…」），
        # 所以選項要在「名稱：」處切斷，否則名稱會被吃進選項裡。
        options = [
            m.split("名稱：")[0].strip()
            for m in marks
            if not m.startswith(_LOCATION_PREFIXES)
        ]
        options = [o for o in options if o]

        name_hit = _NAME_RE.search(line)
        qty_hit = _QUANTITY_RE.search(line)
        dist_hit = _DISTANCE_RE.search(line)
        base = {
            "name": name_hit.group(1).strip() or None if name_hit else None,
            "quantity": int(qty_hit.group(1)) if qty_hit else None,
            "in_segment": True if "●本區段內" in line else (False if "●本區段外" in line else None),
            "distance_m": _to_number(dist_hit.group(1)) if dist_hit else None,
            # 未圈選但填了名稱的列也要留（交流道欄填「名稱：無交流道」但兩個
            # 圈都沒點——「無」本身就是事實，丟掉就無從判斷這一項的等級）。
            "marked": bool(marks),
        }
        if options:
            entries.extend({**base, "option": o} for o in options)
            continue

        entry = {**base, "option": None}
        # 沒有選項也沒有名稱、只有位置與距離的行，是上一筆被儲存格折行拆開的下半段
        # （「名稱：新北市金山地區農會 數量:1」換行「○本區段內 ●本區段外(距 210 M)」）。
        # 真正的第二個設施一定會自己帶「名稱：」，所以這樣分辨不會把兩個設施併成一個。
        if entries and entry["name"] is None and entry["quantity"] is None:
            prev = entries[-1]
            if prev["distance_m"] is None and prev["in_segment"] is None:
                prev["distance_m"] = entry["distance_m"]
                prev["in_segment"] = entry["in_segment"]
                prev["marked"] = prev["marked"] or entry["marked"]
                continue
        entries.append(entry)

    numeric = None
    unit = None
    flat = raw.replace(" ", "")
    for value, u in _NUMBER_UNIT_RE.findall(raw):
        if "距" + value in flat:
            continue  # 距離已經在 entries 裡，不要再當成本欄的量測值
        numeric = _to_number(value)
        unit = u.upper()
        break

    # 有圈選框的格子沒有「純文字填答」可言：那些不含 ○● 的行都是被排版折斷的
    # 選項標籤碎片（「○垃圾場或掩／埋場」的下半段、「變電所或高壓／鐵塔」的下半段），
    # 當成填答會顯示出「埋場」這種看不懂的值。這種格子的事實在 entries 裡。
    has_checkbox = "○" in raw or "●" in raw
    plain = (
        ""
        if has_checkbox
        else "\n".join(
            line
            for line in raw.split("\n")
            if line
            and "名稱：" not in line
            and any("一" <= ch <= "鿿" for ch in line)
        )
    )

    return {
        "raw": raw,
        "entries": entries,
        "numeric": numeric,
        "unit": unit,
        "text": plain or None,
    }


def _to_number(text: str) -> float | int:
    n = float(text.replace(",", ""))
    return int(n) if n == int(n) else n
