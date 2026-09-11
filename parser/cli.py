"""辨識器命令列入口：把官方書表 PDF 印成 JSON。

`python -m parser.cli <pdf> [表別]`

在 API 出現之前，這是驗證辨識結果最快的方式；有了 API 之後它仍然有用——
可以不啟動服務就重現任何一份 PDF 的辨識輸出，用於回歸比對。
"""

from __future__ import annotations

import argparse
import json
import sys

from .detect import detect_table, find_page
from .extract import load_pages
from . import table4

PARSERS = {"表4": table4.parse}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="官方查估書表辨識器")
    ap.add_argument("pdf", help="書表 PDF 路徑")
    ap.add_argument("table", nargs="?", help="表別（表1 / 表5-2 / 表4）；省略則列出各頁表別")
    ap.add_argument("--provenance", action="store_true", help="一併輸出每個欄位的來源")
    args = ap.parse_args(argv)

    pages = load_pages(args.pdf)

    if not args.table:
        for p in pages:
            print("p%-2d %s" % (p.number, detect_table(p) or "（非書表：圖或其他）"))
        return 0

    parse = PARSERS.get(args.table)
    if parse is None:
        print(
            "尚未實作 %s 的辨識器，目前可用：%s" % (args.table, "、".join(PARSERS)),
            file=sys.stderr,
        )
        return 2

    result = parse(find_page(pages, args.table))
    out = result.to_dict()
    if args.provenance:
        out["provenance"] = result.provenance.to_dict()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
