"""把版面加上值畫成 PDF。

值只畫在 template 的 slot 裡。沒有給值的 slot 留白——**不回填原檔的內容**。
這條很重要：如果沒給值就默默用原檔的值，產出來的表會看起來很完整，
但沒人分得出哪些格子是系統算的、哪些是原檔留下的。留白很醜，可是誠實。
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .template import FormTemplate, Slot

# 原檔嵌的是 DFKaiShu-SB（標楷體），系統的 kaiu.ttf 是同一套字體。
FONT_NAME = "TWKai"
FONT_PATHS = (
    r"C:/Windows/Fonts/kaiu.ttf",
    r"C:/Windows/Fonts/mingliu.ttc",
    r"/usr/share/fonts/truetype/arphic/ukai.ttc",
    r"/Library/Fonts/Arial Unicode.ttf",
    r"/System/Library/Fonts/STHeiti Light.ttc",
    r"/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
)

_registered = False


def ensure_font() -> str:
    global _registered
    if _registered:
        return FONT_NAME
    for path in FONT_PATHS:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont(FONT_NAME, path))
            _registered = True
            return FONT_NAME
    raise FileNotFoundError(
        "找不到中文字型。書表全是中文，沒有字型就只會產出一片空白，"
        "所以這裡直接失敗而不是靜靜地畫不出字。找過：%s" % (FONT_PATHS,)
    )


def render(tpl: FormTemplate, values: dict[str, str], out_path: str | Path) -> Path:
    font = ensure_font()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out), pagesize=(tpl.width, tpl.height))
    c.setTitle("%s（系統產出）" % tpl.code)

    # 順序不能換：填色 → 框線 → 文字。先畫線的話底色會蓋掉線。
    for r in tpl.fills:
        col = r.get("color")
        if isinstance(col, (list, tuple)) and len(col) == 3:
            c.setFillColor(Color(*col))
        elif isinstance(col, (int, float)):
            c.setFillGray(col)
        else:
            continue
        c.rect(r["x0"], r["y0"], r["x1"] - r["x0"], r["y1"] - r["y0"], stroke=0, fill=1)

    c.setStrokeGray(0)
    for r in tpl.strokes:
        c.setLineWidth(r["linewidth"])
        c.rect(r["x0"], r["y0"], r["x1"] - r["x0"], r["y1"] - r["y0"], stroke=1, fill=0)
    for ln in tpl.lines:
        c.setLineWidth(ln["linewidth"])
        c.line(ln["x0"], ln["y0"], ln["x1"], ln["y1"])

    c.setFillGray(0)
    for ch in tpl.static_chars:
        c.setFont(font, ch["size"])
        c.drawString(ch["baseline_x"], ch["baseline_y"], ch["text"])

    for path, slot in tpl.slots.items():
        text = values.get(path)
        if text in (None, ""):
            continue
        _draw_slot(c, font, slot, str(text), tpl.height)

    c.save()
    return out


def _draw_slot(c: canvas.Canvas, font: str, slot: Slot, text: str, page_height: float) -> None:
    """把值畫進一格。多行值依換行分行，整體在格內垂直置中。

    字寬超出格寬時**縮小字級**而不是讓它溢出去——書表的格子很窄，
    溢出去會蓋到隔壁欄的內容，看起來像辨識錯誤。
    """
    lines = text.split("\n")
    size = slot.size
    x0, top, x1, bottom = slot.bbox
    width = x1 - x0

    height = bottom - top
    longest = max(pdfmetrics.stringWidth(ln, font, size) for ln in lines)
    if longest > width - 2 and longest > 0:
        size = max(3.5, size * (width - 2) / longest)
    # 也要顧高度：勘查表有幾格塞了 4–5 筆設施，只縮寬度的話會直接溢出格外，
    # 蓋到上下兩列的內容，看起來像辨識錯誤。
    if len(lines) * size * 1.15 > height - 1:
        size = max(3.5, (height - 1) / (len(lines) * 1.15))

    leading = size * 1.15
    block = leading * len(lines)
    # PDF 原點在左下，slot 的 top/bottom 是從上往下量的，所以要換算。
    y_top = page_height - top
    y = y_top - (bottom - top - block) / 2 - size

    c.setFont(font, size)
    for line in lines:
        if slot.align == "left":
            x = x0 + 1
        elif slot.align == "right":
            x = x1 - 1 - pdfmetrics.stringWidth(line, font, size)
        else:
            x = slot.cx - pdfmetrics.stringWidth(line, font, size) / 2
        c.drawString(x, y, line)
        y -= leading
