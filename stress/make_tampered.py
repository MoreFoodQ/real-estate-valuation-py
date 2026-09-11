"""產生「填錯版本」的查估書表，用來演示審查功能。

為什麼需要這個：官方範本是正確的，77 格全部相符。所有的檢核與合理性檢查
都只在異常輸入時才會顯示，拿官方範本走一遍看不出系統做了什麼。

做法是把改壞的值填回官方版面（沿用 pdfform 的正常流程），產出的 PDF 看起來
就是一份估價師填的書表，只是某幾格填錯了。丟進系統就能看到審查結果。

⚠️ 這些是**合成的測試資料**，不是真實案件。檔名都帶 `tampered-` 前綴。

用法：python -m stress.make_tampered
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import paths
from api.kernel_api import appraise_table4, classify, load_ruleset, lookup
from parser import table1, table4, table5_2
from parser.detect import detect_table
from parser.extract import load_pages
from pdfform import template
from pdfform.fill import build_values
from pdfform.forms import FILE_STEMS, INPUT_ONLY_PREFIXES, PARSERS
from pdfform.render import render

OUT = Path(__file__).resolve().parent / "tampered"

# 每個情境：檔名後綴、說明、要覆寫哪些欄位
# 鍵的格式與 pdfform.fill.build_values 的輸出一致。
SCENARIOS: tuple[tuple[str, str, dict[str, dict[str, str]]], None | str] = (
    (
        "grade",
        "表1 主要道路寬度等級 3（普通）改成 2（稍優）。"
        "量測值仍是 18M，所以第一層會抓到「量測值與等級不符」，"
        "第二層會抓到「表1 與表5-2 等級不一致」——一格錯，兩層亮燈。",
        {"表1": {"grades.regional.transport.main_road_width.grade": "2"}},
    ),
    (
        "regional-total",
        "表4 區域因素調整百分率 0.00% 改成 -3.75%（模擬跨表抄錯）。"
        "這是命題文件直接點名的痛點。第三層會抓到與表5-2 總修正數不符，"
        "並算出單價差額 -7,986 元/㎡。",
        {"表4": {"comparables[1].regional_adjustment_pct": "-3.75%"}},
    ),
    (
        "negative-price",
        "表4 土地正常單價改成 -184,763（模擬辨識吃到負號）。"
        "修正前系統會算出負的補償金並回報「相符」；"
        "現在合理性檢查會標記「輸入值有疑慮」。",
        {"表4": {"comparables[1].normal_unit_price": "-184,763"}},
    ),
    (
        "all",
        "以上三種錯誤同時出現。",
        {
            "表1": {"grades.regional.transport.main_road_width.grade": "2"},
            "表4": {
                "comparables[1].regional_adjustment_pct": "-3.75%",
                "comparables[1].normal_unit_price": "-184,763",
            },
        },
    ),
)


def main() -> int:
    src = paths.require(paths.SAMPLE_FORMS_PDF)
    pages = load_pages(src)

    parsed: dict[str, Any] = {}
    boxes: dict[str, dict[str, tuple]] = {}
    page_no: dict[str, int] = {}
    for code, parse in PARSERS.items():
        hits = [p for p in pages if detect_table(p) == code]
        if not hits:
            continue
        result = parse(hits[0])
        parsed[code] = result.to_dict()
        page_no[code] = hits[0].number
        boxes[code] = {
            path: tuple(s.bbox)
            for path, s in result.provenance.entries.items()
            if s.bbox is not None
            and not path.startswith(INPUT_ONLY_PREFIXES.get(code, ()))
        }

    regional = load_ruleset("jinshan_commercial_regional")
    individual = load_ruleset("jinshan_commercial_individual")
    base_values = build_values(
        parsed, regional, individual, appraise_table4, classify, lookup
    )

    OUT.mkdir(parents=True, exist_ok=True)
    print("產出位置：%s\n" % OUT)

    for suffix, note, overrides in SCENARIOS:
        # 只改被指定的欄位，其餘沿用正常流程算出來的值
        values = {code: dict(v) for code, v in base_values.items()}
        for code, kv in overrides.items():
            for key, new in kv.items():
                old = values[code].get(key)
                values[code][key] = new
                print("  [%s] %s：%r → %r" % (suffix, key, old, new))

        made = []
        for code in ("表1", "表5-2", "表4"):
            if code not in parsed:
                continue
            tpl = template.build(src, page_no[code], code, boxes[code])
            out = OUT / ("tampered-%s-%s.pdf" % (suffix, FILE_STEMS[code]))
            render(tpl, values[code], out)
            made.append(out.name)

        print("  → %s" % "、".join(made))
        print("     %s\n" % note)

    print("這些是合成的測試資料，不是真實案件。")
    print("把 tampered-<情境>-*.pdf 三張合併後丟進系統，或單獨丟表4 也能看到部分結果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
