"""欄位級來源記錄。

每一個抽出來的值都要能指回「PDF 第幾頁、哪個位置、原始文字是什麼、走哪條 backend」。
這不是 debug 用的附加品，而是本系統對評審的核心論述——
「每個結論都能指回來源，我們沒讓 AI 生成任何數字」——的資料基礎。
所以 provenance 從第一天就跟值一起產生，不是事後補的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldSource:
    """一個欄位的來源。

    `backend` 記錄這個值是文字層直接讀出來的，還是 vision 模型看圖看出來的。
    審查報告必須把兩者分開陳述：文字層是確定的，vision 是有信心水準的。
    """

    page: int
    bbox: tuple[float, float, float, float] | None
    raw_text: str
    backend: str = "text_layer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "bbox": None if self.bbox is None else [round(v, 2) for v in self.bbox],
            "raw_text": self.raw_text,
            "backend": self.backend,
        }


@dataclass
class Provenance:
    """欄位路徑 → 來源。路徑用 golden JSON 的鍵路徑，例如
    `benchmark.facts.individual.road.frontage_road_width`。
    """

    entries: dict[str, FieldSource] = field(default_factory=dict)

    def record(self, path: str, source: FieldSource) -> None:
        self.entries[path] = source

    def to_dict(self) -> dict[str, Any]:
        return {k: v.to_dict() for k, v in sorted(self.entries.items())}
