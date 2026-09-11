"""從官方書表抽出版面。

官方沒有提供空白 xls，所以「不得擅自修改各欄位名稱、格式」這條規定沒有
可遵循的檔案。折衷做法是**把版面從官方已填書表裡抽出來重繪**：

- 框線是向量物件（line / rect），抽出來的座標就是官方的座標
- 靜態欄位名是文字，抽出來的位置與字級也是官方的
- 只有「值」那些格子被清空，換成我們算出來的內容

所以輸出的每一條線、每一個欄位名都來自官方檔案，不是照著螢幕畫的。
差別只在字型：原檔嵌的是 DFKaiShu（標楷體），我們用系統的 kaiu.ttf，
同一套字體的不同版本，字寬會有極小差異。

「值在哪一格」由三支辨識器的 provenance 提供——它們本來就記了每個欄位的
bbox，這裡直接拿來當填值的位置。這也是為什麼 provenance 要從第一天就做對：
它同時是追溯鏈、是審查依據、也是產表的版面定義。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

BBox = tuple[float, float, float, float]

# 判定「這個字屬於哪個值欄位」時容許的邊界誤差。
# 太小會把貼著格線的字漏掉、太大會把隔壁格的字吃進來。
INSIDE_TOL = 1.0


@dataclass(frozen=True)
class Slot:
    """一個可填的欄位。`align` 與 `size` 都是從原檔的內容學來的，不是猜的。"""

    path: str
    bbox: BBox
    align: str  # left | center | right
    size: float
    original: str

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2


@dataclass
class FormTemplate:
    """一頁書表的版面。座標一律沿用原檔（原點左上、單位 pt）。"""

    code: str
    width: float
    height: float
    fills: list[dict[str, Any]] = field(default_factory=list)
    strokes: list[dict[str, Any]] = field(default_factory=list)
    lines: list[dict[str, Any]] = field(default_factory=list)
    static_chars: list[dict[str, Any]] = field(default_factory=list)
    slots: dict[str, Slot] = field(default_factory=dict)


def _inside(char: dict[str, Any], box: BBox) -> bool:
    cx = (char["x0"] + char["x1"]) / 2
    cy = (char["top"] + char["bottom"]) / 2
    x0, top, x1, bottom = box
    return x0 - INSIDE_TOL <= cx <= x1 + INSIDE_TOL and top - INSIDE_TOL <= cy <= bottom + INSIDE_TOL


def _infer_align(chars: list[dict[str, Any]], box: BBox) -> str:
    """從原檔在這一格裡的排法推斷對齊方式。

    書表裡數值多半置中、名稱多半靠左，但沒有規律可循——與其寫一堆
    per-field 設定，不如量原檔的左右留白：兩邊差不多就是置中。
    """
    if not chars:
        return "center"
    left = min(c["x0"] for c in chars) - box[0]
    right = box[2] - max(c["x1"] for c in chars)
    if left <= 1.5:
        return "left"
    if right <= 1.5:
        return "right"
    return "center" if abs(left - right) <= max(2.0, 0.25 * (left + right)) else "left"


def build(pdf_path: str | Path, page_number: int, code: str, boxes: dict[str, BBox]) -> FormTemplate:
    """抽出一頁的版面。`boxes` 是「欄位路徑 → 該欄位的格子」，來自 provenance。"""
    with pdfplumber.open(str(pdf_path)) as doc:
        page = doc.pages[page_number - 1]
        tpl = FormTemplate(code=code, width=page.width, height=page.height)

        for r in page.rects:
            item = {
                "x0": r["x0"],
                "y0": r["y0"],
                "x1": r["x1"],
                "y1": r["y1"],
                "linewidth": r.get("linewidth") or 0.5,
            }
            if r.get("fill"):
                tpl.fills.append({**item, "color": r.get("non_stroking_color")})
            if r.get("stroke"):
                tpl.strokes.append(item)

        for ln in page.lines:
            tpl.lines.append(
                {
                    "x0": ln["x0"],
                    "y0": ln["y0"],
                    "x1": ln["x1"],
                    "y1": ln["y1"],
                    "linewidth": ln.get("linewidth") or 0.5,
                }
            )

        # 基線取自 text matrix 的平移項，不用 bbox 底部。
        # 用 bbox 底部畫出來會整頁下移，而且不同字級的位移量不同——
        # 「(元/M²)」的上標 2 會脫離同一個詞，讓辨識器再也找不到那個欄位標籤。
        chars = [
            {
                "text": c["text"],
                "x0": c["x0"],
                "x1": c["x1"],
                "baseline_x": (c.get("matrix") or (0,) * 5 + (c["y0"],))[4],
                "baseline_y": (c.get("matrix") or (0,) * 5 + (c["y0"],))[5],
                "top": c["top"],
                "bottom": c["bottom"],
                "size": c.get("size") or 8.0,
            }
            for c in page.chars
        ]

    claimed: set[int] = set()
    for path, box in boxes.items():
        owned = [i for i, c in enumerate(chars) if i not in claimed and _inside(c, box)]
        cs = [chars[i] for i in owned]
        claimed.update(owned)
        tpl.slots[path] = Slot(
            path=path,
            bbox=box,
            align=_infer_align(cs, box),
            # 取最大而非平均：同一格裡混著中文與數字時字級不同，
            # 取平均會被小的那個拉低，填出來的字明顯比鄰欄小一號。
            size=max((c["size"] for c in cs), default=7.1),
            original="".join(c["text"] for c in sorted(cs, key=lambda c: (round(c["top"]), c["x0"]))),
        )

    tpl.static_chars = [c for i, c in enumerate(chars) if i not in claimed]
    return tpl
