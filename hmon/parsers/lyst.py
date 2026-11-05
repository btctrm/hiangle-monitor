"""Lyst（时尚聚合站，英国站 lyst.co.uk；美国站搜不到）。

搜索页 /search/?q=hiangle：<script data-hypernova-key="Feed"><!--{json}--></script>，
  productFeed.feed_items[].product_card（id / url / short_description / in_stock）。
商品页：<script data-hypernova-key="InStockProductPage"><!--{json}--></script>，
  productArea.buy_options[]（每个零售商）.sizes[]（display_size / in_stock / price_info / sale_price_info）。
尺码码制：只有 cfg.uk_retailers 里列出的零售商（默认 adidas-uk，页面就是 adidas.co.uk 的 UK 码）按 UK 解析，
其他零售商只认带码制的写法（"UK 8" 等，to_uk AUTO），否则标码制不明。
请求数：搜索 1 + 商品页 ≤ max_products（默认 4）。
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.parse

from ..core import IN, OUT, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_HI = re.compile(r"hi[\s-]?angle", re.I)


def _hypernova(page: str, key: str):
    m = re.search(r'data-hypernova-key="' + key + r'"[^>]*><!--(.*?)--></script>', page, re.S)
    if not m:
        return None
    try:
        return json.loads(htmllib.unescape(m.group(1)))
    except ValueError:
        return None


def _amount(info) -> float | None:
    a = (info or {}).get("amount")
    return float(a) if a not in (None, "") else None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    base = "https://" + cfg.get("domain", "www.lyst.co.uk")
    q = urllib.parse.quote_plus(cfg.get("search", "hiangle"))
    try:
        page = fetch(f"{base}/search/?q={q}")
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    feed = _hypernova(page, "Feed")
    if not feed or "productFeed" not in feed:
        return StoreResult(store=sid, ok=False, error="搜索页找不到 Feed 数据（可能改版或被拦截）")
    cards = []
    for it in feed["productFeed"].get("feed_items") or []:
        pc = it.get("product_card") or {}
        if pc.get("url") and _HI.search(pc.get("short_description", "")):
            cards.append(pc)
    found = {str(pc["id"]): pc for pc in cards}
    uk_retailers = set(cfg.get("uk_retailers", ["adidas-uk"]))
    res = StoreResult(store=sid, ok=True)
    for pid, pc in list(found.items())[: int(cfg.get("max_products", 4))]:
        url = base + pc["url"]
        try:
            ppage = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        pd = _hypernova(ppage, "InStockProductPage") or _hypernova(ppage, "OutOfStockProductPage")
        area = (pd or {}).get("productArea") or {}
        if "buy_options" not in area:
            return StoreResult(store=sid, ok=False, error=f"{url}: 找不到 buy_options")
        prod = area.get("product") or {}
        title = prod.get("short_description") or pc.get("short_description", "")
        gender = {"M": "M", "F": "W", "W": "W"}.get(pc.get("gender") or "", None) or gender_from_title(title)
        res.products_checked.add(pid)
        for bo in area["buy_options"]:
            slug = bo.get("retailer_slug", "")
            rname = bo.get("retailer_name", slug)
            sizes = bo.get("sizes") or []
            if not sizes:  # 零售商没给尺码：只记一条整体状态
                res.obs.append(
                    Obs(store=sid, product_id=pid, title=f"{title} @ {rname}", url=url,
                        variant_id=f"{slug}|-", raw_size="（未分尺码）", uk=None, color=prod.get("color", ""),
                        price=_amount(bo.get("sale_price_info")) or _amount(bo.get("price_info")),
                        currency=(bo.get("price_info") or {}).get("currency_code") or cfg.get("currency", "GBP"),
                        status=IN if bo.get("in_stock") else OUT, condition="new",
                        note=f"Lyst 零售商 {rname}")
                )
                continue
            for z in sizes:
                raw = str(z.get("display_size") or z.get("raw_size") or "")
                if slug in uk_retailers:
                    uk = to_uk(raw, "UK", gender)
                else:
                    uk = to_uk(raw, "AUTO", gender)
                price = _amount(z.get("sale_price_info")) or _amount(z.get("price_info"))
                res.obs.append(
                    Obs(
                        store=sid,
                        product_id=pid,
                        title=f"{title} @ {rname}",
                        url=url,
                        variant_id=f"{slug}|{raw}",
                        raw_size=raw,
                        uk=uk,
                        color=prod.get("color", ""),
                        price=price,
                        currency=(z.get("price_info") or {}).get("currency_code") or cfg.get("currency", "GBP"),
                        status=IN if z.get("in_stock") else OUT,
                        condition="new",
                        note=f"Lyst 零售商 {rname}",
                    )
                )
    for k in cfg.get("_known_products", []):
        if k not in found:
            res.gone_products.add(k)
    return res
