"""產生合成規則集，用來驗證「規則是資料，不是程式碼」。

做法是把金山商業用地的規則集做等比變換：級距乘 band_scale、
修正幅度乘 step_scale。關鍵在於 max_range 必須跟著 step 一起變，
否則 validate 會報 MAX_RANGE_MISMATCH（實測 step 單獨 ×2 會產生 28 個 ERROR）。

產出的檔案刻意放在 stress/fixtures/ 而不是 kernel/rules/，
避免出現在 /api/rulesets 清單裡被誤認為系統真的支援那些行政區。

用法：python -m stress.make_rulesets
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from api.kernel_api import RULES_DIR, check_ruleset, load_ruleset
from src.validate import errors, warnings

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# (檔名, 行政區, 用地別, 級距倍率, 修正幅度倍率)
VARIANTS = (
    ("testdistrict-residential-regional", "測試區", "住宅用地", 1.5, 2.0),
    ("testdistrict2-industrial-regional", "測試二區", "工業用地", 0.8, 0.5),
)


def scale(raw: dict, ruleset_id: str, district: str, land_use: str,
          band_scale: float, step_scale: float) -> dict:
    r = copy.deepcopy(raw)
    r["ruleset_id"] = ruleset_id
    r["scope"] = {**r.get("scope", {}), "district": district, "land_use": land_use}
    r["status"] = "synthetic"
    r["completeness"] = {
        "note": "壓力測試用的合成規則集，非官方資料。"
                "由金山商業用地規則集等比變換產生（級距×%s、修正幅度×%s）。"
                % (band_scale, step_scale),
    }

    for f in r["factors"]:
        cl = f.get("classifier", {})
        if cl.get("type") == "numeric_bands":
            for band in cl.get("bands", []):
                # or_ranges 的子區間也要一起縮放，否則會產生級距缺口
                for rng in band.get("or_ranges", [band]):
                    for key in ("min", "max"):
                        if isinstance(rng.get(key), (int, float)):
                            rng[key] = round(rng[key] * band_scale, 2)

        m = f.get("matrix", {})
        if m.get("kind") == "linear_step":
            m["step"] = round(float(m["step"]) * step_scale, 4)
        elif m.get("kind") == "cells":
            m["cells"] = [[round(x * step_scale, 4) for x in row] for row in m["cells"]]
        # max_range 是「矩陣[優][劣]」的獨立佐證值，必須同步縮放
        f["max_range"] = round(float(f["max_range"]) * step_scale, 4)

    return r


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    base = json.loads(
        (RULES_DIR / "jinshan_commercial_regional.json").read_text(encoding="utf-8")
    )

    rc = 0
    for name, district, land_use, bs, ss in VARIANTS:
        raw = scale(base, name, district, land_use, bs, ss)
        path = FIXTURES / f"{name}.json"
        path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        rs = load_ruleset(path)
        found = check_ruleset(rs)
        errs, warns = errors(found), warnings(found)
        print("%-38s 級距×%-4s step×%-4s → ERROR=%d WARN=%d"
              % (name, bs, ss, len(errs), len(warns)))
        for e in errs[:3]:
            print("    ERROR %s: %s" % (e.code, e.message[:100]))
            rc = 1

    print()
    print("寫到 %s" % FIXTURES)
    print("ERROR 必須為 0；WARN 多半是 MOI_CAP_EXCEEDED（修正幅度放大後超出內政部上限），")
    print("那是合成資料的預期結果，不是程式問題。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
