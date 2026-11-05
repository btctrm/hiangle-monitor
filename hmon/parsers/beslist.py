"""beslist.nl（荷兰比价站）。

搜索页 /products/r/hiangle/ 的 JSON-LD ItemList 列出商品（name / url / AggregateOffer）；
商品页 JSON-LD Product.offers.offers[] 给出每家店的 price / availability / seller.name。
beslist 不按尺码拆 offer（页面“Maat”字段是混杂的筛选值，不可信），所以尺码一律码制不明：
每条 Obs = 某商品 × 某家店，variant_id = 店名。
请求数：搜索 1 + 商品页 ≤ max_products（默认 4）。
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle", re.I)
_BASE = "https://www.beslist.nl"


def _ld_objs(html: str):
    for block in _LD.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        for x in d if isinstance(d, list) else [d]:
            if isinstance(x, dict):
                yield x


def _pid(url: str) -> str:
    m = re.search(r"/(V4_[0-9a-f-]+)/?", url)
    return m.group(1) if m else url.split("?")[0]


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    q = urllib.parse.quote(cfg.get("search", "hiangle"))
    try:
        html = fetch(f"{_BASE}/products/r/{q}/")
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    items = []
    for x in _ld_objs(html):
        if x.get("@type") == "ItemList":
            for el in x.get("itemListElement") or []:
                it = el.get("item") or {}
                if _HI.search(it.get("name", "")) and it.get("url"):
                    items.append(it)
            break
    else:
        return StoreResult(store=sid, ok=False, error="搜索页没有 JSON-LD ItemList（可能改版或被拦截）")

    res = StoreResult(store=sid, ok=True)
    found = {_pid(it["url"]): it for it in items}
    for pid, it in list(found.items())[: int(cfg.get("max_products", 4))]:
        url = _BASE + it["url"].split("?")[0]
        try:
            phtml = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        prod = next((x for x in _ld_objs(phtml) if x.get("@type") == "Product" and x.get("offers")), None)
        if not prod:
            return StoreResult(store=sid, ok=False, error=f"{url}: 找不到 Product offers")
        agg = prod.get("offers")
        if isinstance(agg, list):
            offers = agg
        elif isinstance(agg, dict) and isinstance(agg.get("offers"), list):
            offers = agg["offers"]
        elif isinstance(agg, dict) and agg.get("@type") == "Offer":
            offers = [agg]
        else:
            return StoreResult(store=sid, ok=False, error=f"{url}: offers 结构不对（{type(agg).__name__}）")
        if not offers and isinstance(agg, dict) and str(agg.get("offerCount", "0")) not in ("0", ""):
            return StoreResult(store=sid, ok=False, error=f"{url}: offerCount={agg.get('offerCount')} 但没有 offers 明细")
        title = prod.get("name") or it.get("name", "")
        gtin = prod.get("gtin13", "")
        res.products_checked.add(pid)
        seen = set()
        for o in offers:
            seller = ((o.get("seller") or {}).get("name") or "").strip()
            if not seller:
                continue  # 没有店名就没有稳定的 variant_id，跳过
            if seller.lower() in seen:  # 同店多条只取第一条（最低价在前）
                continue
            seen.add(seller.lower())
            avail = str(o.get("availability", "")).rsplit("/", 1)[-1]
            status = IN if avail == "InStock" else OUT if avail in ("OutOfStock", "SoldOut", "Discontinued") else UNKNOWN
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=f"{title} @ {seller}",
                    url=url,
                    variant_id=seller.lower(),
                    raw_size="（比价站未分尺码）",
                    uk=None,
                    color="",
                    price=float(o["price"]) if o.get("price") not in (None, "") else None,
                    currency=o.get("priceCurrency") or cfg.get("currency", "EUR"),
                    status=status,
                    condition="new",
                    note=f"beslist 商户 {seller}；{avail or '?'}；GTIN {gtin}",
                )
            )
    for k in cfg.get("_known_products", []):
        if k not in found:
            res.gone_products.add(k)
    return res
