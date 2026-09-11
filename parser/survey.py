"""把表1 勘查表的一格轉成「可以分級的值」。

放在 parser 而不是 api，是因為這件事屬於「表1 寫了什麼」的解讀，
不屬於審查邏輯——審查與產表兩邊都要用它，放在 api 會讓 pdfform
反向依賴 api。它不 import kernel（方向以字串參數傳入），所以層次是乾淨的。
"""

from __future__ import annotations

from typing import Any


def survey_value(survey: dict[str, Any], direction: str) -> tuple[Any, str] | None:
    """把表1 的一格轉成可以餵給 classify 的值。回傳 (值, 取值理由)，取不出來回傳 None。

    表1 的欄位有五種寫法，各自的取值規則不同：

    1. 量測值（建蔽率 70%、主要道路 18M）→ 直接用數字
    2. 文字填答（都市計畫內、已完全開發、顧客通行量多）→ 直接用文字
    3. 圈選在區段內（●本區段內）→ 「區段內有」，那是正面設施的最優級
    4. 圈選在區段外並填距離 → 用距離
    5. 兩個圈都沒點、名稱填「無」→ 缺值，交給級距的「或無」規則判

    第 3 種對嫌惡設施要反過來處理：那些細項的級距沒有「區段內有」這一級
    （優是「3,000m以上」），設施就在區段內反而是最糟的情形，所以換算成距離 0。

    多設施時**取最近**。手冊 p.24 說「以對當地地價影響最大者填寫」——
    對嫌惡設施而言最近的最糟，對正面設施而言最近的最好，兩邊都是取最近，
    所以這條規則不需要分方向。Golden Case 佐證：電業設施變電所 700m 與
    儲油槽 440m，表5-2 填 5 劣，正是取 440m 的結果。
    """
    if survey.get("numeric") is not None:
        return survey["numeric"], "表1 量測值 %s%s" % (
            survey["numeric"],
            survey.get("unit") or "",
        )
    if survey.get("text"):
        return survey["text"], "表1 填答「%s」" % survey["text"]

    marked = [e for e in survey.get("entries") or [] if e.get("marked")]

    if any(e.get("in_segment") for e in marked):
        names = "、".join(e.get("option") or e.get("name") or "" for e in marked if e.get("in_segment"))
        if direction == "farther_is_better":
            return 0, "表1 圈選「本區段內」（%s）；此為嫌惡設施，區段內視同距離 0" % names
        return "區段內有", "表1 圈選「本區段內」（%s）" % names

    distances = [e["distance_m"] for e in marked if e.get("distance_m") is not None]
    if distances:
        nearest = min(distances)
        if len(distances) > 1:
            return nearest, "表1 圈選 %d 個設施 %s，取最近 %sm（手冊 p.24 以影響最大者填寫）" % (
                len(distances),
                distances,
                nearest,
            )
        return nearest, "表1 距離 %sm" % nearest

    if marked:
        return None  # 有圈選但既無距離也非區段內，無法判讀

    return None, "表1 未圈選任何設施、名稱填「無」"
