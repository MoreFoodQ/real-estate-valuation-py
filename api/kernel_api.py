"""接進 kernel 的唯一入口。

kernel 是獨立的零依賴專案，內部套件名叫 `src`（由 `kernel/conftest.py` 把
`kernel/` 放上 path）。api 各處直接寫 `from src.compute import ...` 會讓
「這是哪個 src」變得不明確，也讓相依方向藏在檔案深處。
所以路徑接線與更名都集中在這一個檔案，其他 api 模組只從這裡拿東西——
這樣「api 依賴 kernel、kernel 不依賴 api」這條規定看一眼就能驗證。
"""

from __future__ import annotations

import sys

from paths import ROOT

_KERNEL_DIR = ROOT / "kernel"
if str(_KERNEL_DIR) not in sys.path:
    sys.path.insert(0, str(_KERNEL_DIR))

from src.classify import Grade, classify  # noqa: E402
from src.compute import (  # noqa: E402
    ComparableResult,
    Table4Result,
    appraise_table4,
    round_up_by_tier,
    trial_price,
)
from src.matrix import lookup  # noqa: E402
from src.ruleset import RULES_DIR, RuleSet, load_moi_caps, load_ruleset  # noqa: E402
from src.validate import check_ruleset, errors as validation_errors  # noqa: E402
from src.validate import warnings as validation_warnings  # noqa: E402

__all__ = [
    "ComparableResult",
    "Grade",
    "RULES_DIR",
    "RuleSet",
    "Table4Result",
    "appraise_table4",
    "check_ruleset",
    "classify",
    "load_moi_caps",
    "load_ruleset",
    "lookup",
    "round_up_by_tier",
    "trial_price",
    "validation_errors",
    "validation_warnings",
]
