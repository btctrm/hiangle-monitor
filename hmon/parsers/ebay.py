"""eBay 官方 Browse API（item_summary/search）。

免费：在 developer.ebay.com 注册应用，拿 Production 的 App ID（Client ID）和 Cert ID（Client Secret），
放进环境变量 EBAY_APP_ID / EBAY_CERT_ID（GitHub Actions secrets）。没配就跳过（ok=True，不算失效）。

流程（每店每轮 ≤ 1 + max_pages 次请求）：
  1. POST https://api.ebay.com/identity/v1/oauth2/token  grant_type=client_credentials,
     scope=https://api.ebay.com/oauth/api_scope（应用令牌约 2 小时有效，进程内缓存，同一轮多个站点共用一次）
  2. GET  https://api.ebay.com/buy/browse/v1/item_summary/search?q=…&limit=200&filter=…
     请求头 X-EBAY-C-MARKETPLACE-ID: EBAY_US / EBAY_GB / EBAY_DE / …，按 response["next"] 翻页。

每条在售 listing 视为“有货”（单件 variant_id="1"）；本轮搜索成功但没再出现 = 下架（gone_products）。
成色按 conditionId（eBay 官方条件编号）判断，没有再看 condition 文字和标题关键词。
尺码只从标题里认：先 to_uk(AUTO)（显式 UK/EU/US/cm），再按站点的惯用码制认 “Size 9 / Gr. 42 / Taille 42”：
  EBAY_GB → UK；EBAY_DE/FR/IT/ES → EU（只认 33–50）；EBAY_US → 美码且标题能看出男女才换算；其他站不猜。
多尺码 listing（itemGroupType=SELLER_DEFINED_VARIANTS）尺码记“码制不明”，备注里说明。
"""
from __future__ import annotations

import base64
import os
import re
import time

import requests

from ..core import IN, UA, Obs, StoreResult
from ..sizes import eu_to_uk, gender_from_title, to_uk

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

_TOKEN: dict = {}  # {"t": token, "exp": epoch}

_NAME_PAT = re.compile(r"hi[\s-]?angle|ハイアングル|하이앵글", re.I)
# 配件/非鞋：标题含这些就丢掉
_ACCESSORY_PAT = re.compile(
    r"\b(box only|empty box|insoles?|einlegesohle|laces?|schnürsenkel|lacets|sticker|keychain|"
    r"resol(e|ing)|rubber only|poster)\b",
    re.I,
)

# conditionId → 本项目成色（见 developer.ebay.com sell/static/metadata/condition-id-values）
_COND_ID = {
    "1000": "new",       # New / New with box / New with tags
    "1500": "new",       # New other / New without box / without tags
    "1750": "like_new",  # New with defects
    "2000": "like_new", "2010": "like_new", "2020": "used", "2030": "used", "2500": "like_new",
    "2750": "like_new",  # Like New
    "2990": "like_new",  # Pre-owned - Excellent（服饰类）
    "3000": "used",      # Used / Pre-owned - Good
    "3010": "used",      # Pre-owned - Fair
    "4000": "used", "5000": "used", "6000": "used",
}
_SKIP_COND = {"7000"}  # For parts or not working

_TITLE_NEW = re.compile(r"\b(nwt|nib|bnib|bnwt|brand new|new with box|neu|ovp|ungetragen|neuf|nuovo|nuove)\b", re.I)
_TITLE_LIKE_NEW = re.compile(r"\b(like new|wie neu|worn once|comme neuf|très bon état|come nuov[oe])\b", re.I)
_TITLE_USED = re.compile(r"\b(used|pre-?owned|gebraucht|getragen|worn|occasion|usat[oe])\b", re.I)

# 站点惯用码制（标题里只有“Size 9”这种裸数字时用）
_SITE_SYSTEM = {
    "EBAY_GB": "UK", "EBAY_IE": "UK",
    "EBAY_DE": "EU", "EBAY_AT": "EU", "EBAY_CH": "EU", "EBAY_FR": "EU", "EBAY_IT": "EU",
    "EBAY_ES": "EU", "EBAY_NL": "EU", "EBAY_BE": "EU", "EBAY_PL": "EU",
    "EBAY_US": "US",
}
_BARE_SIZE = re.compile(
    r"(?:\bsize|\bsz\.?|\bgr\.|\bgröße|\bgroesse|\bgr\b|\btaille|\bpointure|\btaglia|\btg\.?|\btalla|\bmaat)"
    r"\s*[:.]?\s*(\d{1,2}(?:[.,]5| ?[12]/3|⅓|⅔)?)(?![\d/])",
    re.I,
)


class _ApiError(Exception):
    pass


def _token(force: bool = False) -> str | None:
    app, cert = os.environ.get("EBAY_APP_ID"), os.environ.get("EBAY_CERT_ID")
    if not app or not cert:
        return None
    if not force and _TOKEN.get("t") and _TOKEN.get("exp", 0) > time.time() + 120:
        return _TOKEN["t"]
    auth = base64.b64encode(f"{app}:{cert}".encode()).decode()
    try:
        r = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": UA},
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=25,
        )
    except requests.RequestException as e:
        raise _ApiError(f"eBay 取令牌失败：{e.__class__.__name__}")
    if r.status_code != 200:
        raise _ApiError(f"eBay 取令牌失败：HTTP {r.status_code} {r.text[:150]}")
    try:
        j = r.json()
        _TOKEN["t"] = j["access_token"]
    except (ValueError, KeyError):
        raise _ApiError("eBay 取令牌失败：返回不是预期 JSON")
    _TOKEN["exp"] = time.time() + int(j.get("expires_in") or 7200)
    return _TOKEN["t"]


def _get(url: str, params: dict | None, marketplace: str, tok: str) -> dict:
    headers = {
        "Authorization": f"Bearer {tok}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
        "Accept": "application/json",
        "User-Agent": UA,
    }
    last = ""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=25)
        except requests.RequestException as e:
            last = e.__class__.__name__
            time.sleep(2 + attempt * 3)
            continue
        if r.status_code == 401 and attempt == 0:  # 令牌过期：刷新一次
            tok = _token(force=True) or tok
            headers["Authorization"] = f"Bearer {tok}"
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(2 + attempt * 3)
            continue
        if r.status_code != 200:
            raise _ApiError(f"eBay 搜索失败：HTTP {r.status_code} {r.text[:150]}")
        try:
            j = r.json()
        except ValueError:
            raise _ApiError("eBay 搜索失败：返回的不是 JSON（可能被拦截）")
        if not isinstance(j, dict):
            raise _ApiError("eBay 搜索失败：返回结构不对")
        return j
    raise _ApiError(f"eBay 搜索失败：{last}")


def _condition(it: dict, title: str) -> str:
    cid = str(it.get("conditionId") or "")
    if cid in _COND_ID:
        return _COND_ID[cid]
    text = (it.get("condition") or "").lower()
    if text:
        if any(w in text for w in ("defect", "mängel", "fehler", "défaut", "difett")):
            return "like_new"
        if "like new" in text or "excellent" in text:
            return "like_new"
        if text.startswith("new") or text.startswith("neu") or text.startswith("neuf") or text.startswith("nuovo"):
            return "new"
        if any(w in text for w in ("used", "pre-owned", "gebraucht", "occasion", "usato")):
            return "used"
    if _TITLE_LIKE_NEW.search(title):
        return "like_new"
    if _TITLE_USED.search(title):
        return "used"
    if _TITLE_NEW.search(title):
        return "new"
    return "unknown"


_MENS_NUM = re.compile(r"\b(men'?s|mens|women'?s|womens)(\s*)(?=\d)", re.I)


def _size(title: str, marketplace: str) -> float | None:
    g = gender_from_title(title)
    if marketplace != "EBAY_US":
        # to_uk(AUTO) 把 “Mens 8” 当美码；英/欧/澳站的 “Mens 8” 通常是本地码，改成裸 “size 8” 交给下面按站点码制处理
        title = _MENS_NUM.sub(r"\1 size ", title)
    uk = to_uk(title, "AUTO", g)
    if uk is not None:
        return uk
    system = _SITE_SYSTEM.get(marketplace)
    if not system:
        return None
    vals = {m.group(1).replace(",", ".") for m in _BARE_SIZE.finditer(title)}
    if len(vals) != 1:  # 没有或互相矛盾：不猜
        return None
    raw = vals.pop().replace("⅓", " 1/3").replace("⅔", " 2/3")
    if system == "EU":
        m = re.fullmatch(r"(\d{2})(?:\.5| ?([12]/3))?", raw)
        if not m or not (33 <= int(m.group(1)) <= 50):
            return None
        return eu_to_uk(re.sub(r"(\d{2}) ?([12]/3)", r"\1 \2", raw))
    if "/" in raw:
        return None
    if system == "UK":
        return to_uk(raw, "UK")
    if system == "US":
        return to_uk(raw, "US", g) if g in ("M", "W") else None
    return None


def _money(p: dict | None) -> tuple[float | None, str | None]:
    if not isinstance(p, dict):
        return None, None
    try:
        v = float(p.get("value"))
    except (TypeError, ValueError):
        return None, p.get("currency")
    return v, p.get("currency")


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    mkt = cfg.get("marketplace", "EBAY_US")
    try:
        tok = _token()
    except _ApiError as e:
        return StoreResult(store=sid, ok=False, error=str(e))
    if tok is None:
        return StoreResult(store=sid, ok=True, error="未配置 eBay 密钥，已跳过")

    filters = [cfg.get("buying_options_filter", "buyingOptions:{FIXED_PRICE|BEST_OFFER}")]
    if cfg.get("item_location_country"):
        filters.append(f"itemLocationCountry:{cfg['item_location_country']}")
    if cfg.get("extra_filter"):
        filters.append(cfg["extra_filter"])
    params = {
        "q": cfg.get("search", "hiangle"),
        "limit": int(cfg.get("limit", 200)),
        "filter": ",".join(f for f in filters if f),
    }
    if cfg.get("category_ids"):
        params["category_ids"] = str(cfg["category_ids"])

    items: list[dict] = []
    url, p = SEARCH_URL, params
    try:
        for _ in range(max(1, int(cfg.get("max_pages", 2)))):
            j = _get(url, p, mkt, tok)
            if "itemSummaries" not in j and "total" not in j:
                return StoreResult(store=sid, ok=False, error="eBay 返回结构不对（没有 itemSummaries/total）")
            items.extend(x for x in (j.get("itemSummaries") or []) if isinstance(x, dict))
            nxt = j.get("next")
            if not nxt:
                break
            url, p = nxt, None
        else:
            if nxt:  # 翻页上限内没取完：不确定哪些真的消失了
                return StoreResult(store=sid, ok=False,
                                   error=f"eBay 结果超过 {cfg.get('max_pages', 2)} 页，未取完（请收窄 search）")
    except _ApiError as e:
        return StoreResult(store=sid, ok=False, error=str(e))

    res = StoreResult(store=sid, ok=True)
    seen: set[str] = set()
    for it in items:
        title = (it.get("title") or "").strip()
        iid = str(it.get("legacyItemId") or it.get("itemId") or "")
        if not iid or iid in seen or not _NAME_PAT.search(title) or _ACCESSORY_PAT.search(title):
            continue
        if str(it.get("conditionId") or "") in _SKIP_COND:
            continue
        price, cur = _money(it.get("price"))
        if price is None:
            continue
        seen.add(iid)
        res.products_checked.add(iid)
        ship_v, ship_c = None, None
        for so in it.get("shippingOptions") or []:
            v, c = _money((so or {}).get("shippingCost"))
            if v is not None and (ship_v is None or v < ship_v):
                ship_v, ship_c = v, c
        loc = (it.get("itemLocation") or {}).get("country", "?")
        multi = it.get("itemGroupType") == "SELLER_DEFINED_VARIANTS" or "itemGroupHref" in it
        uk = None if multi else _size(title, mkt)
        note = f"eBay 成色：{it.get('condition') or '未知'}；所在地 {loc}"
        if ship_v is not None:
            note += f"；运费 {ship_v:g} {ship_c or cur}"
        if multi:
            note += "；多尺码 listing（价格为最低价，尺码见页面）"
        res.obs.append(
            Obs(
                store=sid,
                product_id=iid,
                title=title,
                url=it.get("itemWebUrl", ""),
                variant_id="1",
                raw_size="多尺码" if multi else title,
                uk=uk,
                color="",
                price=price,
                currency=cur or cfg.get("currency", "USD"),
                status=IN,
                condition=_condition(it, title),
                note=note,
            )
        )
    known = set(cfg.get("_known_products", []))
    res.gone_products = known - res.products_checked
    return res
