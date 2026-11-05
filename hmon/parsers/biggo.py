"""BigGo（美国比价/搜索聚合，biggo.com）：一次请求看到 Amazon US、eBay US、adidas US 的 Hiangle 列表。

搜索页 /s/<q>/ 是 Next.js 服务端渲染，self.__next_f.push([1,"…"]) 里有
{"initValue":{"ssrData":{"total":…,"list":[…]}}}，list[] 每条：
  item_id（"us_bid_ebay:298730438074"）/ nindex（来源）/ title / purl（原站链接）/ price / currency /
  is_expired / is_notfound / is_offline
每条 = 一个 listing（variant_id "1"），列出即视为在售；本轮消失 = 下架。
成色：eBay 按标题关键词判断（NEW/NWOB/New In Box → new；used/worn/damaged/resole → used；否则 unknown），
Amazon / adidas 官网 → new。尺码：to_uk(AUTO)；美国站 "Women's … Size 6" 这类按美码 + 性别换算。
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_HI = re.compile(r"hi[\s-]?angle", re.I)
_BRAND = re.compile(r"five\s*ten|5\.10|fiveten|adidas", re.I)
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_SRC = {"us_bid_ebay": "eBay US", "us_mall_amazon": "Amazon US", "us_ec_adidas": "adidas US"}


def _ssr(page: str) -> dict | None:
    try:
        txt = "".join(json.loads('"' + m.group(1) + '"') for m in _PUSH.finditer(page))
    except ValueError:
        return None
    i = txt.find('"ssrData"')
    if i < 0:
        return None
    j = txt.rfind("{", 0, i)
    try:
        obj, _ = json.JSONDecoder().raw_decode(txt, j)
    except ValueError:
        return None
    return obj.get("ssrData")


def _condition(title: str, nindex: str) -> str:
    t = title.lower()
    if re.search(r"\bused\b|\bworn\b|damaged|resole|pre-?owned|gently", t):
        return "used"
    if re.search(r"like new|worn once|lightly", t):
        return "like_new"
    if re.search(r"\bnew\b|\bnwob\b|\bnwt\b|\bnib\b|new in box|brand new|unworn|never worn", t):
        return "new"
    if "_bid_" in nindex:
        return "unknown"
    return "new"  # Amazon / 品牌官网


def _size(title: str) -> float | None:
    g = gender_from_title(title)
    uk = to_uk(title, "AUTO", g)
    if uk is None and g:
        m = re.search(r"\bsize\s*(\d{1,2}(?:\.5)?)\b", title, re.I)
        if m:  # 美国站：Size N = 美码
            uk = to_uk(m.group(1), "US", g)
    return uk


def _pid(it: dict) -> str:
    """稳定的 listing id：eBay 的 item_id 是 BigGo 的长哈希（不保证跨次稳定），改用原站链接里的 eBay 商品号；
    Amazon / adidas 的 item_id 就是 ASIN / 货号，直接用。"""
    purl = str(it.get("purl") or "")
    m = re.search(r"ebay\.com/itm/(?:[^/?#]*/)?(\d{9,})", purl)
    if m:
        return f"us_bid_ebay:{m.group(1)}"
    iid = str(it.get("item_id") or "")
    if "_bid_" in iid:  # 拍卖类却拿不到原站商品号：宁可不收，避免 key 漂移误推“新上架”
        return ""
    return iid


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    q = urllib.parse.quote(cfg.get("search", "hiangle"))
    url = f"https://biggo.com/s/{q}/"
    try:
        page = fetch(url)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    sd = _ssr(page)
    if not sd or not isinstance(sd.get("list"), list):
        return StoreResult(store=sid, ok=False, error="找不到 ssrData.list（可能改版或被拦截）")
    res = StoreResult(store=sid, ok=True)
    for it in sd["list"]:
        title = str(it.get("title") or "").replace("\u2019", "'")
        if not (_HI.search(title) and _BRAND.search(title)):
            continue
        if it.get("is_expired") or it.get("is_notfound") or it.get("is_offline") or it.get("is_ad"):
            continue
        pid = _pid(it)
        if not pid or pid in res.products_checked:
            continue
        res.products_checked.add(pid)
        nindex = str(it.get("nindex") or "")
        src = _SRC.get(nindex) or (it.get("store") or {}).get("name") or nindex
        res.obs.append(
            Obs(
                store=sid,
                product_id=pid,
                title=title,
                url=it.get("purl") or url,
                variant_id="1",
                raw_size=title,
                uk=_size(title),
                color="",
                price=float(it["price"]) if it.get("price") else None,
                currency=it.get("currency") or cfg.get("currency", "USD"),
                status=IN,
                condition=_condition(title, nindex),
                note=f"BigGo 来源：{src}",
            )
        )
    # 只看 1 页：结果总数超过本页条数时，没出现的旧 listing 可能只是排到后面，不记下架
    try:
        complete = int(sd.get("total") or 0) <= len(sd["list"])
    except (TypeError, ValueError):
        complete = False
    if complete:
        for k in cfg.get("_known_products", []):
            if k not in res.products_checked:
                res.gone_products.add(k)
    return res
