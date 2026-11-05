"""北美 / 日韩台二手组（used_us_asia）共用小工具：Hiangle 过滤、尺码、成色关键词、价格、下架判断。

不是解析器（没有 scan），只给 poshmark / kijiji / sidelineswap / yahoo_auctions_jp / rakuma /
jimoty / daangn / bunjang / novelship / ruten 调用。

尺码（卖家自由文本，宁缺毋滥）：
  1. 先做 NFKC 规范化（全角数字 → 半角）和 "7 1/2" → "7.5"；
  2. 交给 to_uk(AUTO)：显式 "UK 6" "EU 42 2/3" "US M 9" "26.5cm" "245mm"；
  3. 再认 "JP26" / "JP 26.5"（日本码 = cm）；韩国标题里孤立的 220–300（5 的倍数）= mm；
  4. "US 8" 没写男女时，只在标题明确写男/女款时换算，否则返回 None（码制不明）。
"""
from __future__ import annotations

import html as _html
import re
import unicodedata

from ..sizes import gender_from_title, to_uk

HI = re.compile(r"hi[\s\-]?angle|ハイアングル|하이앵글", re.I)
# 日韩“ハイアングル/하이앵글”还指相机机位、汽车配件、韩国服装品牌，所以要求同时出现鞋/品牌词
BRAND = re.compile(
    r"five\s*ten|5\.10|(?<!\d)510(?!\d)|fiveten|ファイブテン|파이브텐|adidas|アディダス|아디다스|"
    r"climb|クライミング|ボルダリング|클라이밍|암벽|볼더링",
    re.I,
)
# 明显不是一双鞋：多双打包、只卖单只
BUNDLE = re.compile(r"일괄|まとめ売り|セット売り|\bbundle\b|\blot\b|single shoe|(?:left|right) shoe only|片足のみ|한짝", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").replace("’", "'").replace("‘", "'")
    s = re.sub(r"(\d)\s*(?:-|\s)\s*1/2\b", r"\1.5", s)  # "7 1/2" / "7-1/2" → 7.5
    s = re.sub(r"(\d{2})\s*-\s*([12]/3)", r"\1 \2", s)  # "EU 46-2/3" → "EU 46 2/3"
    s = re.sub(r"((?:Men|Women)'?s)\s+size\s*", r"\1 ", s, flags=re.I)  # "Women's Size 7.5" → "Women's 7.5"
    return s


def fix_mojibake(text: str) -> str:
    """服务器没在 Content-Type 里写 charset 时，requests 会按 ISO-8859-1 解码 UTF-8 页面。这里还原。"""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def is_hiangle(title: str, desc: str = "", need_brand: bool = False) -> bool:
    t = norm(title)
    m = HI.search(t)
    if not m:
        return False
    # "hi angle" / "hi-angle" 分开写时也常指相机机位、支架等，必须同时有品牌/攀岩词
    spaced = bool(re.fullmatch(r"hi[\s\-]angle", m.group(0), re.I))
    if (need_brand or spaced) and not BRAND.search(t + " " + norm(desc)):
        return False
    return True


def is_bundle(title: str) -> bool:
    return bool(BUNDLE.search(title or ""))


def gender_of(title: str) -> str | None:
    g = gender_from_title(title or "")
    if g:
        return g
    t = title or ""
    if re.search(r"\bW\b|ウィメンズ|여자|여성|우먼", t):
        return "W"
    if re.search(r"남자|남성", t):
        return "M"
    return None


def size_from_text(title: str, desc: str = "", korean_mm: bool = False) -> tuple[str, float | None]:
    """返回 (原文片段, UK 码或 None)。"""
    g = gender_of(title)
    for t in (norm(title), norm(desc)):
        if not t:
            continue
        uk = to_uk(t, "AUTO", g)
        if uk is not None:
            for m in re.finditer(r"\b(?:UK|EU|US)\s*(?:M|W|Men'?s|Women'?s)?\s*[\d.]+(?:\s[12]/3)?|\d{2,3}(?:\.5)?\s*(?:cm|mm)\b|"
                                 r"\b(?:Men'?s|Women'?s)\s*[\d.]+", t, re.I):
                if to_uk(m.group(0), "AUTO", g) == uk:
                    return (m.group(0), uk)
            return (t[:40], uk)
        m = re.search(r"\bJP\s*(\d{2}(?:\.5)?)(?![\d.])", t, re.I)
        if m:
            uk = to_uk(m.group(1) + "cm", "AUTO")
            if uk is not None:
                return (m.group(0), uk)
    if korean_mm:
        m = re.search(r"(?<![\d.,])(2[2-9][05])(?![\d.,])", norm(title))
        if m:
            uk = to_uk(m.group(1) + "mm", "AUTO")
            if uk is not None:
                return (m.group(0) + "(mm)", uk)
    return ("", None)


# ---- 成色关键词（平台字段优先，由各解析器处理）----
_LIKE_NEW = re.compile(
    r"like\s*new|as\s*new|nearly\s*new|hardly\s*(?:worn|used)|(?:worn|used|tried\s*on)\s*(?:once|twice)|"
    r"ほぼ未使用|未使用に近い|数回使用|[1一]回のみ|一度のみ|試着のみ|"
    r"거의\s*새|새것\s*같|s급|(?:1|한)\s*(?:회|번)\s*(?:착용|신)|"
    r"近全新|九成新|9成新",
    re.I,
)
_USED = re.compile(
    r"(?<!never )(?<!un)\bused\b|(?<!never )(?<!un)\bworn\b|\bscuff|\bpre-?owned|\bpreloved|signs of (?:light )?wear|"
    r"中古|使用感|使用済|傷や汚れ|"
    r"중고|사용감|착용감|"
    r"二手",
    re.I,
)
_NEW = re.compile(
    r"brand\s*new|\bnew\b|unworn|never\s*worn|\bbnib\b|\bnwt\b|\bnib\b|"
    r"未使用|新品|タグ付|"
    r"새상품|미사용|새제품|미착용|새\s*신발|"
    r"全新",
    re.I,
)


def condition_from_text(*texts: str) -> str:
    t = " ".join(norm(x) for x in texts if x)
    if _LIKE_NEW.search(t):
        return "like_new"
    if _USED.search(t):
        return "used"
    if _NEW.search(t):
        return "new"
    return "unknown"


def merge_condition(platform: str | None, text_cond: str) -> str:
    """平台字段优先；平台说“新”但文字写“近新/有痕迹”时取更保守的那个。"""
    if not platform or platform == "unknown":
        return text_cond
    if platform == "new" and text_cond in ("like_new", "used"):
        return text_cond
    if platform == "like_new" and text_cond == "used":
        return "used"
    return platform


def parse_price(s) -> float | None:
    """'15,000円' / '¥19,800' / '$75.00' / 219000 → 数字。"""
    if isinstance(s, (int, float)):
        return float(s)
    s = norm(clean(str(s or "")))
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def finish(res, cfg: dict):
    """本轮搜索成功时，旧 listing 没再出现 = 下架。"""
    known = set(cfg.get("_known_products", []))
    res.gone_products = known - res.products_checked
    return res
