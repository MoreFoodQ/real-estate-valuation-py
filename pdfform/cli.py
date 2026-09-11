"""產表命令列入口：`python -m pdfform.cli <pdf> <輸出目錄>`

不啟動服務就能產出三張書表，也方便把產出的檔案再餵回辨識器做回歸比對。
"""

from __future__ import annotations

import argparse
import sys

import paths
from api.kernel_api import appraise_table4, classify, load_ruleset, lookup

from .forms import build_forms


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="產出填好的官方查估書表 PDF")
    ap.add_argument("pdf", nargs="?", help="查估書表 PDF；省略則用官方範本")
    ap.add_argument("out_dir", nargs="?", default="out", help="輸出目錄（預設 out/）")
    ap.add_argument("--ruleset-individual", default="jinshan_commercial_individual")
    ap.add_argument("--ruleset-regional", default="jinshan_commercial_regional")
    args = ap.parse_args(argv)

    src = args.pdf or str(paths.require(paths.SAMPLE_FORMS_PDF))
    try:
        written = build_forms(
            src,
            args.out_dir,
            regional=load_ruleset(args.ruleset_regional),
            individual=load_ruleset(args.ruleset_individual),
            appraise=appraise_table4,
            classify=classify,
            lookup=lookup,
        )
    except (ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 1

    for code, path in written.items():
        print("%-6s %s（%.0f KB）" % (code, path, path.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
