"""產出三張填好的官方書表 PDF。

一次呼叫從 PDF 進、三個 PDF 出：辨識 → 計算 → 填回官方版面。
版面來自哪裡、值從哪裡來，分別見 `template.py` 與 `fill.py` 的說明。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import paths
from parser import table1, table4, table5_2
from parser.detect import detect_table
from parser.extract import Page, load_pages

from . import template
from .fill import FORM_CODES, build_values
from .render import render

PARSERS = {"表1": table1.parse, "表5-2": table5_2.parse, "表4": table4.parse}

# 檔名用 ASCII：這些檔會被下載、被壓縮、被丟到別的系統裡，
# 中文檔名在跨平台傳遞時很容易變成亂碼。
FILE_STEMS = {"表1": "table1-survey", "表5-2": "table5_2-regional", "表4": "table4-comparison"}


def build_forms(
    pdf_path: str | Path,
    out_dir: str | Path,
    *,
    regional: Any,
    individual: Any,
    appraise,
    classify,
    lookup,
    source_pdf: str | Path | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Path]:
    """辨識 `pdf_path`，算完，把三張表填回官方版面並輸出 PDF。

    `source_pdf` 是版面來源，預設就用輸入的那份——官方書表的版面在自己
    的檔案裡，沒有理由去別的地方拿。只有輸入本身不是官方版面（例如
    掃描件重建）時才需要指定另一份當版面樣板。

    `warnings` 傳進來的話，會把「取了第一頁」「找不到某張表」之類需要人工
    知道的事情 append 上去。三張書表是交付物，少一張不能靜默發生。
    """
    pages = load_pages(pdf_path)
    layout_pdf = Path(source_pdf) if source_pdf else Path(pdf_path)

    parsed: dict[str, Any] = {}
    boxes: dict[str, dict[str, tuple[float, float, float, float]]] = {}
    page_no: dict[str, int] = {}

    for code, parse in PARSERS.items():
        page = _find(pages, code, warnings)
        if page is None:
            if warnings is not None:
                warnings.append(
                    {
                        "code": "table_not_found",
                        "table": code,
                        "message": "這份 PDF 裡找不到 %s，不會產出該張書表。" % code,
                    }
                )
            continue
        result = parse(page)
        parsed[code] = result.to_dict()
        page_no[code] = page.number
        boxes[code] = {
            path: tuple(src.bbox)
            for path, src in result.provenance.entries.items()
            if src.bbox is not None and not _input_only(code, path)
        }

    if not parsed:
        raise ValueError("這份 PDF 裡找不到任何可辨識的查估書表（表1／表5-2／表4）")

    values = build_values(parsed, regional, individual, appraise, classify, lookup)

    out_dir = Path(out_dir)
    written: dict[str, Path] = {}
    for code in FORM_CODES:
        if code not in parsed:
            continue
        tpl = template.build(layout_pdf, page_no[code], code, boxes[code])
        written[code] = render(
            tpl, values[code], out_dir / ("%s.pdf" % FILE_STEMS[code])
        )
    return written


# 表1 的量測值是現場調查的輸入，系統不重算也不重畫——它留在靜態層，
# 等於原封不動保留官方原稿。系統對表1 的貢獻只有等級與級數。
#
# 這也順便避開一個實務問題：那些格子有合併儲存格與折行的子標籤
# （電業設施的「變電所或高壓鐵塔／瓦斯槽或儲油槽」分兩列畫），
# 重畫時很容易與靜態層疊字。
INPUT_ONLY_PREFIXES = {"表1": ("surveys.",)}


def _input_only(code: str, path: str) -> bool:
    return path.startswith(INPUT_ONLY_PREFIXES.get(code, ()))


def _find(
    pages: list[Page],
    code: str,
    warnings: list[dict[str, Any]] | None = None,
) -> Page | None:
    """找出某張表所在的那一頁。重複出現時取第一頁並發警告。

    原本的做法是 `find_page()` 加 `except LookupError: return None`，而
    `find_page` 對「出現在多頁」也是 raise。結果同一份 PDF 裡表4 跨頁時：

      /api/parse  → 取第一頁繼續跑，審查正常
      /api/forms  → LookupError 被吞掉 → 整張表跳過，只產出兩張書表

    兩條路徑對同一份輸入給出不同結果，而且產表那邊沒有任何訊息說明少了哪張。
    三張書表是交付物（勘查表須上傳），少一張不能靜默發生。

    現在與 `api/main.py` 的辨識邏輯一致：都取第一頁。跨頁合併是另一件事，
    需要先有跨頁的實際書表才能做。
    """
    hits = [p for p in pages if detect_table(p) == code]
    if not hits:
        return None
    if len(hits) > 1 and warnings is not None:
        warnings.append(
            {
                "code": "table_on_multiple_pages",
                "table": code,
                "pages": [p.number for p in hits],
                "message": "%s 出現在第 %s 頁，已採用第 %d 頁。"
                "若該表實際跨頁，後續頁面的內容不會被讀取，請人工確認。"
                % (code, "、".join(str(p.number) for p in hits), hits[0].number),
            }
        )
    return hits[0]


def default_source() -> Path:
    return paths.require(paths.SAMPLE_FORMS_PDF)
