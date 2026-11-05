"""欧洲二手平台（used_eu 组）共用的小工具：Hiangle 过滤、标题/描述里的尺码、成色关键词、下架判断。

不是解析器（没有 scan），只给 kleinanzeigen / willhaben / recommerce_nordic / bazos /
marktplaats / gumtree_uk / allegro_lokalnie 调用。

尺码规则（二手卖家自由文本，宁缺毋滥）：
  1. 先交给 to_uk(AUTO)：显式 "UK 6" "EU 42 2/3" "US M 9" "26.5cm"；
  2. 再认“尺码关键词 + 两位数”：Gr. 44 / Größe 40 2/3 / maat 41 1/3 / str 37 1/3 / veľkosť 42 /
     rozmiar 40 / taille 42 → 按 EU（Five Ten 官方 1/3 码表）；
  3. 最后只在标题里认一个孤立的 34–49 两位数（欧洲二手站默认 EU），如 "hiangle pro 40"。
  范围写法（"37-38" "44-44,5"）、半码（41.5 不在官方表）一律返回 None（码制不明）。
"""
from __future__ import annotations

import html as _html
import re

from ..sizes import eu_to_uk, gender_from_title, to_uk

HI = re.compile(r"hi[\s\-]?angle|ハイアングル|하이앵글", re.I)

_EU_NUM = r"(\d{2}(?:\s*[.,\-]?\s*[12]/3|\s?[⅓⅔]|[.,]\d{1,2})?)"
_SIZE_WORD = re.compile(
    r"(?:\bgr(?:ö|oe|o)(?:ß|ss|s)e\b|\bgr\b\.?|\bschuhgr(?:ö|oe)(?:ß|ss)e\b|\bsize\b|\bmaat\b|\bstr\b\.?|\bstl\b\.?|"
    r"\bstorlek\b|\bstørrelse\b|\bkoko\b|\bvelikost\b|\bveľkosť\b|\bvel\b\.?|\brozmiar\b|\brozm\b\.?|"
    r"\btaille\b|\btaglia\b|\btalla\b|\bnr\b\.?|\bin\b)\s*[:.]?\s*" + _EU_NUM + r"(?!\d)",
    re.I,
)
_BARE = re.compile(r"(?<![\d.,/€$£])\b((?:3[4-9]|4\d)(?:\s*[.,\-]?\s*[12]/3|\s?[⅓⅔]|[.,]\d{1,2})?)\b(?!\s*(?:€|eur|kr|zł|pln|czk|kč|%|cm|mm|,-))", re.I)
_RANGE_AFTER = re.compile(r"^\s*(?:-|–|/|bis|oder|or|tot)\s*\d{2}", re.I)


def is_hiangle(*texts: str) -> bool:
    return any(t and HI.search(t) for t in texts)


# 求购/交换广告（不是在售）：标题开头的关键词。
_WANTED = re.compile(
    r"^\W*(?:suche|gesuch|kaufe|tausche|wanted|wtb|looking\s*for|iso\b|zoeken|gezocht|ruil|"
    r"koup[ií]m|k[uú]pim|h[lľ]ed[aá]m|kupi[eę]|szukam|zamieni[eę]|ønskes|onskes|søges|soges|köpes|kopes|"
    r"ostetaan|etsitään|etsitaan|cherche|recherche)\b",
    re.I,
)
# 正文提到 Hiangle 但标题点名了别的鞋款/多双打包 → 不能当 Hiangle 收。
_OTHER_MODEL = re.compile(
    r"anasazi|dragon|niad|aleon|crawe|kirigami|rogue|verdon|freerider|quantum|team\s*(?:5\.?10|ten)|coyote|"
    r"arrowhead|moccasym|\basym|stonelands|siren|blackwing|gambit|spire|kestrel|trailcross|impact|sleuth|"
    r"tennie|camp\s*four|mystic|scarpa|la\s*sportiva|evolv|tenaya|ocun|butora|unparallel|red\s*chili|mad\s*rock|"
    r"konvolut|paket|\bset\b|\blot\b|\bpaar\b|\bpairs?\b|\d\s*x\b",
    re.I,
)
_SHOE_TITLE = re.compile(
    r"five\s*ten|fiveten|5[.,]?10|adidas|kletter|boulder|climb|leze[cč]k|lezack|klim|klatre|klätter|"
    r"kiipeily|wspinacz|escalade|arrampicata|escalada",
    re.I,
)


_RESERVED = re.compile(r"\b(?:reserviert|reserved|gereserveerd|rezervov[aá]n[oaé]?|zarezerwowan[ey]|reservert|reserverad|reserveret|varattu|r[ée]serv[ée]e?)\b", re.I)


def is_reserved(*texts: str) -> bool:
    """标题/价格栏写“已预订”：不能确定还能买 → 状态 UNKNOWN。"""
    return any(t and _RESERVED.search(t) for t in texts)


def is_wanted(title: str) -> bool:
    return bool(_WANTED.search(title or ""))


def hiangle_match(title: str, body: str = "") -> tuple[bool, bool]:
    """返回 (是否收, 是否仅靠正文)。标题含 hiangle → 收；否则只有在标题是 Five Ten/攀岩鞋、
    且没点名其他鞋款/多双打包时，才接受正文里的 hiangle。求购/交换广告一律不收。"""
    if is_wanted(title):
        return (False, False)
    if HI.search(title or ""):
        return (True, False)
    if body and HI.search(body) and _SHOE_TITLE.search(title or "") and not _OTHER_MODEL.search(title or ""):
        return (True, True)
    return (False, False)


def _norm_eu(s: str) -> str:
    s = s.replace("⅓", " 1/3").replace("⅔", " 2/3")
    s = re.sub(r"\s*[.,\-]?\s*([12]/3)", r" \1", s)
    return re.sub(r"\s+", " ", s).strip()


def _eu_match(text: str, pat: re.Pattern) -> tuple[str, float | None] | None:
    first = None
    vals = set()
    for m in pat.finditer(text):
        if _RANGE_AFTER.match(text[m.end():]):
            r = (m.group(0).strip(), None)  # 范围写法：不猜
        else:
            r = (m.group(0).strip(), eu_to_uk(_norm_eu(m.group(m.lastindex))))
        if first is None:
            first = r
        vals.add(r[1])
    if first is None:
        return None
    if len(vals) > 1:  # 同一段文字里出现多个不同尺码（如“平时穿 43，这双 45 1/3”）：不猜
        return (first[0], None)
    return first


def size_from_text(title: str, desc: str = "") -> tuple[str, float | None]:
    """返回 (原文片段, UK 码或 None)。"""
    g = gender_from_title(title)
    for t in (title, desc):
        if not t:
            continue
        uk = to_uk(t, "AUTO", g)
        if uk is not None:
            m = re.search(r"\b(?:UK|EU|US)\s*[MW]?\s*[\d.,]+(?:\s[12]/3)?|\d{2}(?:[.,]5)?\s*(?:cm|mm)\b", t, re.I)
            return (m.group(0) if m else t[:40], uk)
        r = _eu_match(t, _SIZE_WORD)
        if r:
            return r
    r = _eu_match(title, _BARE)
    if r:
        return r
    return ("", None)


# ---- 成色（标题+描述关键词；平台字段优先，由各解析器处理）----
_LIKE_NEW = re.compile(
    r"wie\s*neu|neuwertig|neuwärtig|neuzustand|(?:nur\s*)?(?:1\s*x|einmal|ein\s*mal|zweimal|2\s*x)\s*(?:getragen|benutzt|probiert|anprobiert)|"
    r"like\s*new|as\s*new|nearly\s*new|hardly\s*(?:worn|used)|(?:worn|used)\s*(?:once|twice)|"
    r"zo\s*goed\s*als\s*nieuw|als\s*nieuw|"
    r"tr[eè]s\s*bon\s*[ée]tat|comme\s*neuf|"
    r"som\s*ny|nesten\s*ny|næsten\s*ny|nyskick|kuin\s*uusi|"
    r"jak\s*nowe|jako\s*nov|ako\s*nov|"
    r"ほぼ未使用|未使用に近い",
    re.I,
)
_USED = re.compile(
    r"(?<!un)(?<!nie )(?<!nicht )(?<!kaum )gebraucht|(?<!un)(?<!nie )(?<!nicht )getragen|(?<!un)(?<!nie )(?<!nicht )benutzt|besohlt|resol|"
    r"(?<!never )(?<!not )\bused\b|(?<!never )(?<!un)\bworn\b|(?<!niet )(?<!nooit )\bgebruikt\b|(?<!niet )(?<!nooit )(?<!ge)\bgedragen\b|"
    r"\bgood\s*(?:condition|nick)|\bexcellent\s*condition|\bgebrauchsspuren|"
    r"\bbon\s*[ée]tat|\bporté|"
    r"\bbrukt|\banvänd|\bkäytetty|"
    r"(?<!nie)używan|(?<!ne)použit[éáýa]\b|(?<!ne)nošen[éáýa]\b|(?<!ne)nosen[éáýa]\b|"
    r"中古",
    re.I,
)
_NEW = re.compile(
    r"\bneu\b|nagelneu|ungetragen|nie\s*getragen|nicht\s*getragen|ungebraucht|unbenutzt|\bovp\b|"
    r"brand\s*new|\bnew\b|unworn|never\s*worn|\bbnib\b|\bnwt\b|\bbnwt\b|"
    r"\bnieuw|niet\s*gebruikt|nooit\s*gedragen|never\s*used|\bneuf\b|\bneuve?s?\b|"
    r"helt\s*ny|\bubrukt|oanvänd|käyttämätön|\buusi\b|"
    r"\bnow[eya]\b|nieużywan|\bnov[éýá]\b|nepoužit|nenošen|"
    r"未使用|新品|새상품|미사용",
    re.I,
)


def condition_from_text(*texts: str) -> str:
    t = " ".join(x for x in texts if x)
    if _LIKE_NEW.search(t):
        return "like_new"
    if _USED.search(t):
        return "used"
    if _NEW.search(t):
        return "new"
    return "unknown"


def merge_condition(platform: str | None, text_cond: str) -> str:
    """平台字段优先；平台说“新”但文字写“近新/穿过”时取更保守的那个。"""
    if not platform or platform == "unknown":
        return text_cond
    order = {"new": 0, "like_new": 1, "used": 2}
    if platform == "new" and text_cond in ("like_new", "used"):
        return text_cond
    return platform if platform in order else text_cond


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def parse_price(s: str) -> float | None:
    """'80 € VB' / '1.250 €' / '1 500' / '£45.00' / '149,99 zł' → 数字；'VB' 'Dohodou' → None。"""
    s = clean(s).replace(" ", " ")
    m = re.search(r"\d[\d .,']*", s)
    if not m:
        return None
    n = m.group(0).strip().replace(" ", "").replace("'", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", n):  # 1.250,00
        n = n.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", n):  # 1,250.00
        n = n.replace(",", "")
    else:
        n = n.replace(",", ".").rstrip(".")
    try:
        return float(n)
    except ValueError:
        return None


def finish(res, cfg: dict):
    """二手站：本轮搜索成功时，旧 listing 没再出现 = 下架。"""
    known = set(cfg.get("_known_products", []))
    res.gone_products = known - res.products_checked
    return res
