"""外部資料位置。

官方文件放在本專案的 ``docs/`` 下，與程式分開但同一個 repo——這樣 clone
一份就能跑，不必依賴外層目錄結構。也可以用環境變數覆寫，方便部署環境掛載
唯讀文件目錄。

註：專案原本是 monorepo 的一部分，`docs/` 位於上一層（`ROOT.parent`）。
拆成獨立 repo 後改為 `ROOT`。這是唯一一處依賴目錄佈局的程式碼。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DOC_DIR = Path(
    os.environ.get(
        "VALUATION_DOC_DIR",
        ROOT / "docs" / "official" / "real-estate-valuation",
    )
).resolve()

SAMPLE_FORMS_PDF = DOC_DIR / "查估書表範本.pdf"
CRITERIA_PDF = DOC_DIR / "評價基準明細表範例.pdf"
MANUAL_PDF = DOC_DIR / "土地徵收補償市價查估作業手冊.pdf"
NTPC_MANUAL_PDF = DOC_DIR / "新北查估書手冊.pdf"

GOLDEN_CASE = ROOT / "kernel" / "golden" / "case_1140901_99_001.json"


def require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            "找不到 %s。請確認 docs/official/real-estate-valuation 已整理完成，或設定 VALUATION_DOC_DIR "
            "指向文件目錄（目前推定為 %s）。" % (path, DOC_DIR)
        )
    return path
