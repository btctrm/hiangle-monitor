"""通用 schema.org 解析：页面 JSON-LD 里带 ProductGroup/hasVariant 的店铺（如 Trekkinn）。

只接受“每个尺码各有一条 offer”的页面；只有一个总价 offer 的页面不接（分不出尺码）。
cfg 里 list_only_available: true 表示店铺只列出有货尺码，未列出的尺码 = 缺货。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)


def _find_group(obj):
    if isinstance(obj, list):
        for x in obj:
            g = _find_group(x)
            if g:
                return g
    elif isinstance(obj, dict):
        t = obj.get("@type")
        if (t == "ProductGroup" or (isinstance(t, list) and "ProductGroup" in t)) and obj.get("hasVariant"):
            return obj
        for v in obj.values():
            if isinstance(v, (dict, list)):
                g = _find_group(v)
                if g:
                    return g
    return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for i, url in enumerate(cfg["urls"]):
        pid = cfg.get("product_ids", [])[i] if i < len(cfg.get("product_ids", [])) else url
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        group = None
        for block in _LD.findall(html):
            try:
                group = _find_group(json.loads(block))
            except ValueError:
                continue
            if group:
                break
        if not group:
            return StoreResult(store=sid, ok=False, error=f"{url}: 找不到逐码库存数据（可能改版或被拦截）")
        res.products_checked.add(pid)
        title = group.get("name", "")
        gender = cfg.get("gender") or gender_from_title(title)
        for v in group["hasVariant"]:
            off = v.get("offers") or {}
            if isinstance(off, list):
                off = off[0] if off else {}
            avail = str(off.get("availability", "")).rsplit("/", 1)[-1]
            status = IN if avail == "InStock" else OUT if avail in ("OutOfStock", "SoldOut", "Discontinued") else UNKNOWN
            raw = str(v.get("size", ""))
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=str(v.get("url") or url),
                    variant_id=f"{v.get('color', '')}|{raw}",
                    raw_size=raw,
                    uk=to_uk(raw, cfg.get("size_system", "AUTO"), gender),
                    color=str(v.get("color", "")),
                    price=float(off["price"]) if off.get("price") not in (None, "") else None,
                    currency=off.get("priceCurrency") or cfg.get("currency", ""),
                    status=status,
                    condition="new",
                    note="" if status != UNKNOWN else f"availability={avail}",
                )
            )
    return res
