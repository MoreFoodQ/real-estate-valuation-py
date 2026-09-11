"""判斷一頁是哪一張書表。

依頁首標題文字判斷，不依頁碼：官方送來的檔案可能只含其中一張表、
或把幾張表併在一個檔、或夾了區段圖（範本 6 頁裡有 3 頁是圖）。
"""

from __future__ import annotations

from .extract import Page

# 標題關鍵字 → 表別代號。順序有意義：表5-2 的標題含「表5-2」，
# 必須在較短的鍵之前比對，否則會被前綴誤判。
_TITLES: tuple[tuple[str, str], ...] = (
    ("表5-2", "表5-2"),
    ("表1", "表1"),
    ("表4", "表4"),
)

# 各表的正式名稱，用來在標題代號之外做第二重確認。
_NAMES: dict[str, str] = {
    "表1": "地價區段勘查表",
    "表5-2": "影響地價區域因素分析明細表",
    "表4": "比較法調查估價表",
}


def detect_table(page: Page) -> str | None:
    """回傳表別代號（`表1` / `表5-2` / `表4`），無法判定回傳 None。

    要求代號與正式名稱同時出現才算命中。單靠代號會把區段圖誤判
    （圖頁的比例尺、圖例裡也可能出現「表」字樣的片段）。
    """
    head = " ".join(w.text for w in page.words[:12])
    for key, code in _TITLES:
        if key in head and _NAMES[code] in head:
            return code
    return None


def find_page(pages: list[Page], code: str) -> Page:
    hits = [p for p in pages if detect_table(p) == code]
    if not hits:
        raise LookupError("這份 PDF 裡找不到 %s" % code)
    if len(hits) > 1:
        raise LookupError(
            "%s 出現在多頁（%s），無法判斷該用哪一頁"
            % (code, [p.number for p in hits])
        )
    return hits[0]
