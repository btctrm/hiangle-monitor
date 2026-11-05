"""SportsShoes.com（英国，Next.js）。

商品页 __NEXT_DATA__ → props.pageProps.product：
  name / sku / variants[] {sku, ean, prices.price, prices.currencyCode, inventory.isInStock,
  options[0].value[0].label = 英码（EAN 已与其他店核对：4061625307901 = UK 7）}
站内搜索不可用（404），靠 cfg.urls 固定商品页。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

_ND = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle", re.I)


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for url in cfg["urls"]:
        m = re.search(r"/product/([a-z0-9]+)/", url, re.I)
        pid = m.group(1).lower() if m else url
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        m = _ND.search(html)
        try:
            prod = json.loads(m.group(1))["props"]["pageProps"]["product"] if m else None
        except (ValueError, KeyError, TypeError):
            prod = None
        if not prod or not prod.get("variants"):
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到 __NEXT_DATA__ 商品数据（可能改版）")
        title = str(prod.get("name", ""))
        if not _HI.search(title):
            return StoreResult(store=sid, ok=False, error=f"{pid}: 商品名不是 Hiangle：{title}")
        res.products_checked.add(pid)
        color = str(prod.get("manufacturerColor") or "")
        for v in prod["variants"]:
            opts = v.get("options") or []
            group = opts[0].get("group", "") if opts else ""
            raw = str((opts[0].get("value") or [{}])[0].get("label", "")) if opts else ""
            uk = to_uk(raw, "UK") if group == "Adult Footwear Size" else None
            st = (v.get("inventory") or {}).get("isInStock")
            status = IN if st is True else OUT if st is False else UNKNOWN
            pr = v.get("prices") or prod.get("prices") or {}
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=url,
                    variant_id=str(v.get("sku") or v.get("ean") or raw),
                    raw_size=f"UK {raw}" if uk is not None else raw,
                    uk=uk,
                    color=color,
                    price=float(pr["price"]) if pr.get("price") is not None else None,
                    currency=pr.get("currencyCode") or cfg.get("currency", "GBP"),
                    status=status,
                    condition="new",
                    note="" if status != UNKNOWN else f"isInStock={st}",
                )
            )
    return res
