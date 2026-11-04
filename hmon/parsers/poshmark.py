"""Poshmark（美国二手/闲置平台）：搜索页 → 每条 listing 页的 JSON-LD Product。

2026-11-04 实测：搜索页 JSON-LD 是 ItemList（只有链接）；listing 页有 Product，
offers 里带 price / availability（InStock / SoldOut）/ itemCondition（New / Used），
标题如 “Five Ten Hiangle Climbing Shoes Men's Size 8”（美码男）。
每条 listing 只有一个尺码，所以按标题换算尺码；认不出的标“码制不明”。
"""
from __future__ import annotations

import html as _h
import json
import re
from urllib.parse import quote

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..parsers.jsonld import _LD
from ..sizes import gender_from_title, to_uk


def _ld(html: str, typ: str):
    for block in _LD.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for it in data if isinstance(data, list) else [data]:
            if isinstance(it, dict) and it.get("@type") == typ:
                return it
    return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    q = cfg.get("search", "five ten hiangle")
    try:
        page = fetch(f"https://poshmark.com/search?query={quote(q)}&type=listings&availability=available")
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    lst = _ld(page, "ItemList")
    if lst is None:
        return StoreResult(store=sid, ok=False, error="搜索页找不到商品列表（可能改版或被拦截）")
    urls = [x.get("url", "") for x in lst.get("itemListElement", [])]
    urls = [u for u in urls if "hiangle" in u.lower()][: int(cfg.get("max_items", 12))]
    for u in urls:
        pid = u.rstrip("/").rsplit("-", 1)[-1]
        try:
            prod = _ld(fetch(u), "Product")
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{u}: {e}")
        if not prod:
            continue
        title = _h.unescape(prod.get("name", ""))
        if "hiangle" not in title.lower():
            continue
        off = prod.get("offers") or {}
        avail = str(off.get("availability", "")).rsplit("/", 1)[-1]
        status = IN if avail == "InStock" else OUT if avail in ("OutOfStock", "SoldOut", "Discontinued") else UNKNOWN
        cond = str(off.get("itemCondition", "")).rsplit("/", 1)[-1]
        res.products_checked.add(pid)
        res.obs.append(Obs(
            store=sid, product_id=pid, title=title, url=u, variant_id="1", raw_size=title,
            uk=to_uk(title, "AUTO", gender_from_title(title)), color=str(prod.get("color", "")),
            price=float(off["price"]) if off.get("price") not in (None, "") else None,
            currency=off.get("priceCurrency") or "USD", status=status,
            condition="new" if cond.startswith("New") else "used" if cond.startswith("Used") else "unknown",
            note="个人卖家，成色/真伪请看图；Poshmark 可议价",
        ))
    # 搜索结果里消失的（卖掉/下架）按缺货处理
    seen = {u.rstrip("/").rsplit("-", 1)[-1] for u in urls}
    res.gone_products |= set(cfg.get("_known_products", [])) - seen
    return res
