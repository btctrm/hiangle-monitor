"""尺码换算：一律换成 UK 码（Five Ten / adidas 男女款 UK 码对应同一脚长）。

换算来源：Bergfreunde Five Ten 尺码表 https://www.bergfreunde.eu/five-ten-size-chart/
  US 男 = UK + 0.5；US 女 = UK + 1.5；EU 按下表。
解析不出来就返回 None，绝不猜。
"""
from __future__ import annotations

import re
from fractions import Fraction

# EU -> UK（Five Ten 官方表，EU 以 1/3 为步长）
_EU_TO_UK = {
    "36": 3.5, "36 2/3": 4, "37 1/3": 4.5, "38": 5, "38 2/3": 5.5, "39 1/3": 6,
    "40": 6.5, "40 2/3": 7, "41 1/3": 7.5, "42": 8, "42 2/3": 8.5, "43 1/3": 9,
    "44": 9.5, "44 2/3": 10, "45 1/3": 10.5, "46": 11, "46 2/3": 11.5,
    "47 1/3": 12, "48": 12.5, "48 2/3": 13, "49 1/3": 13.5, "50": 14,
    "50 2/3": 14.5, "51 1/3": 15, "52 2/3": 16, "53 1/3": 17, "54 2/3": 18,
}
# 以三分之一为单位的数值键，方便匹配 "42.67"、"42⅔"、"42 2/3"
_EU_THIRDS = {}
for k, v in _EU_TO_UK.items():
    parts = k.split()
    val = Fraction(int(parts[0]))
    if len(parts) == 2:
        val += Fraction(parts[1])
    _EU_THIRDS[val] = v

_UNICODE_FRAC = {"⅓": " 1/3", "⅔": " 2/3", "½": ".5"}


def _norm(s: str) -> str:
    s = str(s).strip()
    for k, v in _UNICODE_FRAC.items():
        s = s.replace(k, v)
    s = s.replace(",", ".")
    return re.sub(r"\s+", " ", s)


def eu_to_uk(eu: str) -> float | None:
    s = _norm(eu)
    m = re.fullmatch(r"(\d{2})(?: (1/3|2/3))?", s)
    if m:
        val = Fraction(int(m.group(1))) + (Fraction(m.group(2)) if m.group(2) else 0)
        return _EU_THIRDS.get(val)
    m = re.fullmatch(r"(\d{2})\.(\d+)", s)  # 42.67 / 43.3 这类小数写法
    if m:
        x = float(s)
        for val, uk in _EU_THIRDS.items():
            if abs(float(val) - x) < 0.1:
                return uk
    return None  # 例如 "41.5"：不是 Five Ten 的 EU 码，拒绝猜


def _num(s: str) -> float | None:
    s = _norm(s)
    if re.fullmatch(r"\d{1,2}(\.5)?", s):
        return float(s)
    return None


def to_uk(raw: str, system: str, gender: str | None = None) -> float | None:
    """raw: 店铺原始尺码文本；system: UK / US_M / US_W / US / EU / AUTO。

    gender 只在 system == 'US' 时用来区分男女款（'M' 或 'W'）。
    """
    s = _norm(raw)
    system = (system or "AUTO").upper()

    if system == "AUTO":
        m = re.search(r"\bUK\s*([\d.]+)", s, re.I) or re.search(r"([\d.]+)\s*\(UK\)", s, re.I)
        if m:
            return _valid_uk(_num(m.group(1)))
        m = re.search(r"\bEU\s*(\d{2}(?: [12]/3|\.\d+)?)", s, re.I)
        if m:
            return eu_to_uk(m.group(1))
        m = re.search(r"\bUS\s*(M|W|Men'?s|Women'?s)?\s*([\d.]+)", s, re.I)
        if m:
            g = (m.group(1) or gender or "").upper()[:1]
            n = _num(m.group(2))
            if n is None or g not in ("M", "W"):
                return None
            return _valid_uk(n - (0.5 if g == "M" else 1.5))
        m = re.search(r"\b(Men'?s|Mens|Women'?s|Womens)\s*([\d.]+)", s, re.I)
        if m:  # 如 “Mens 11/Womens 12”：美码男/女
            n = _num(m.group(2))
            g = "W" if m.group(1).lower().startswith("w") else "M"
            return None if n is None else _valid_uk(n - (0.5 if g == "M" else 1.5))
        return None

    if system == "UK":
        m = re.search(r"([\d.]+)", s)
        return _valid_uk(_num(m.group(1))) if m else None
    if system == "EU":
        m = re.search(r"(\d{2}(?: [12]/3|\.\d+)?)", s)
        return eu_to_uk(m.group(1)) if m else None
    if system in ("US_M", "US_W", "US"):
        g = {"US_M": "M", "US_W": "W"}.get(system, (gender or "").upper()[:1])
        if g not in ("M", "W"):
            return None
        m = re.search(r"([\d.]+)", s)
        n = _num(m.group(1)) if m else None
        return None if n is None else _valid_uk(n - (0.5 if g == "M" else 1.5))
    return None


def _valid_uk(x: float | None) -> float | None:
    if x is None:
        return None
    if 2 <= x <= 18 and (x * 2) == int(x * 2):
        return x
    return None


def gender_from_title(title: str) -> str | None:
    t = title.lower()
    if re.search(r"women|womens|wmn|damen|femme|レディース", t):
        return "W"
    if re.search(r"\bmen'?s\b|\bmens\b|herren|homme|メンズ", t):
        return "M"
    return None


def fmt_uk(x: float | None) -> str:
    if x is None:
        return "码制不明"
    return f"UK {x:g}"
