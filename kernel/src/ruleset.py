"""RuleSet 載入層。

規則是資料，不是程式。Engine 只認識這裡定義的結構，
換行政區／換用地別＝換一份 JSON，程式不動。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


def dec(x: Any, *, field: str | None = None) -> Decimal:
    """一律經字串轉 Decimal，避免二進位浮點誤差污染修正率與價格。

    無法解析時一律轉成 ValueError。Decimal 對不合法字串丟的是 InvalidOperation
    （ArithmeticError 的子類），而 api 層的 except ValueError 接不住它，
    會一路變成 HTTP 500。/api/compute 與 /api/review 接受用戶端傳來的任意
    tables，所以這個轉換必須在這裡做——實測 None、""、"無"、"184,763"
    都會走到這條路。classify.py 對同一個問題已有相同處理。
    """
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (ArithmeticError, TypeError, ValueError) as e:
        where = f"{field}：" if field else ""
        raise ValueError(
            f"{where}無法解析為數字的值 {x!r}。"
            f"若這是從書表讀出來的值，請確認該格是否被誤讀"
            f"（數字欄位不應含逗號、單位或文字）。"
        ) from e


@dataclass(frozen=True)
class Factor:
    factor_id: str
    label: str
    group: str
    grade_count: int
    max_range: Decimal
    matrix: dict
    classifier: dict
    unit: str | None = None
    table4_row: int | None = None
    source_page: int | None = None
    compliance_note: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def grade_labels(self) -> list[str]:
        return self._labels

    def label_of(self, grade: int) -> str:
        return self._labels[grade - 1]


@dataclass(frozen=True)
class RuleSet:
    ruleset_id: str
    scope: dict
    source: dict
    factors: dict[str, Factor]
    grade_labels: dict[int, list[str]]
    # 規則集的頂層欄位（扣掉 factors）。validator 需要 moi_cap_column 之類的
    # 設定，但那些是「這份表怎麼被驗」的設定，不是某個細項的屬性。
    meta: dict = field(default_factory=dict)

    @property
    def factor_ids(self) -> list[str]:
        return list(self.factors)

    def __getitem__(self, factor_id: str) -> Factor:
        try:
            return self.factors[factor_id]
        except KeyError:
            raise KeyError(f"RuleSet {self.ruleset_id} 沒有細項 {factor_id}") from None

    def __len__(self) -> int:
        return len(self.factors)


def load_ruleset(name_or_path: str | Path) -> RuleSet:
    path = Path(name_or_path)
    if not path.exists():
        path = RULES_DIR / f"{name_or_path}.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    labels = {int(k): v for k, v in data["grade_labels"].items()}

    factors: dict[str, Factor] = {}
    for f in data["factors"]:
        n = f["grade_count"]
        if n not in labels:
            raise ValueError(f"{f['factor_id']}: 缺少 {n} 級的 grade_labels 定義")
        fac = Factor(
            factor_id=f["factor_id"],
            label=f["label"],
            group=f.get("group", ""),
            grade_count=n,
            max_range=dec(f["max_range"]),
            matrix=f["matrix"],
            classifier=f["classifier"],
            unit=f.get("unit"),
            table4_row=f.get("table4_row"),
            source_page=f.get("source_page"),
            compliance_note=f.get("compliance_note"),
            raw=f,
        )
        # 少數細項的等級文字與同級數的通用文字不同：二級制的「有無禁止建築」
        # 「有無限制建築」在書表上印的是「無／有」而不是「優／劣」，而同為二級的
        # 「都市計畫（內、外）」印的是「優／劣」。表5-2 的等級文字必須與書表一致
        # （審查重點第 vi 項），所以允許逐細項覆寫。
        object.__setattr__(fac, "_labels", f.get("grade_labels") or labels[n])
        factors[fac.factor_id] = fac

    return RuleSet(
        ruleset_id=data["ruleset_id"],
        scope=data["scope"],
        source=data["source"],
        factors=factors,
        grade_labels=labels,
        meta={k: v for k, v in data.items() if k != "factors"},
    )


def load_moi_caps(path: str | Path | None = None, *, kind: str = "individual") -> dict:
    """內政部最大影響範圍表。

    個別因素在附件25、區域因素在附件24，兩份的欄位軸也不同：
    附件25 分住宅／商業／工業／農業／其他 5 種用地別；
    附件24 的商業用地還要再分高度／中度／普通／村里鄰 4 級。
    所以分成兩個檔，由規則集的 scope.factor_kind 決定載哪一份。
    """
    if path is None:
        path = RULES_DIR / ("moi_caps_regional.json" if kind == "regional" else "moi_caps.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))
