"""Shopify 店铺：站内搜索发现商品 + 读 /products/<handle>.js 的逐码库存。

防误报：
- 只认 inventory_management == "shopify"（库存被跟踪）的变体；不跟踪库存的变体 available 永远为真，记为未知。
- 注意：实测（2026-09-30）SpokeX、Délire 的缺货尺码也能加进购物车（到结账才拦），
  所以“能加购物车”不能当有货证据，本程序不用它。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

SIZE_OPTION_NAMES = ("size", "taille", "pointure", "shoe size", "größe", "grösse", "サイズ")


def _discover(domain: str, query: str) -> list[str]:
    url = (
        f"https://{domain}/search/suggest.json?q={quote(query)}"
        "&resources[type]=product&resources[limit]=10"
        "&resources[options][unavailable_products]=last"
    )
    data = fetch(url, expect_json=True)
    try:
        prods = data["resources"]["results"]["products"]
    except (KeyError, TypeError):
        raise FetchError("搜索接口结构异常")
    handles = []
    for p in prods:
        m = re.search(r"/products/([^/?#]+)", p.get("url", ""))
        if m:
            handles.append((m.group(1), p.get("title", "")))
    return handles


def _condition(cfg: dict, product: dict) -> str:
    mode = cfg.get("condition", "new")
    if mode in ("new", "used"):
        return mode
    tags = [t.lower() for t in product.get("tags", [])]
    title = product.get("title", "").lower()
    for t in cfg.get("used_tags", []):
        if t.lower() in tags:
            return "used"
    if re.search(r"\bused\b|pre-owned|second hand|occasion", title):
        return "used"
    return "unknown"


def scan(cfg: dict) -> StoreResult:
    sid, domain = cfg["id"], cfg["domain"]
    res = StoreResult(store=sid, ok=True)
    must = [w.lower() for w in cfg.get("title_must", ["hiangle"])]
    try:
        found = _discover(domain, cfg.get("search", "hiangle"))
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    handles = {h for h, t in found if all(w in t.lower() for w in must)}
    handles |= set(cfg.get("handles", [])) | set(cfg.get("_known_products", []))

    for h in sorted(handles):
        try:
            p = fetch(f"https://{domain}/products/{h}.js", expect_json=True)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(h)  # 商品已下架：它的所有尺码按缺货处理
                continue
            return StoreResult(store=sid, ok=False, error=f"{h}: {e}")
        title = p.get("title", "")
        if not all(w in title.lower() for w in must):
            continue
        res.products_checked.add(h)
        opts = [o.get("name", "").lower() if isinstance(o, dict) else str(o).lower() for o in p.get("options", [])]
        size_idx = next((i for i, n in enumerate(opts) if n in SIZE_OPTION_NAMES), None)
        if size_idx is None and len(opts) == 1:
            size_idx = 0
        gender = cfg.get("gender") or gender_from_title(title)
        cond = _condition(cfg, p)
        for v in p.get("variants", []):
            raw = (v.get("options") or [None] * 3)[size_idx] if size_idx is not None else v.get("title", "")
            raw = raw or ""
            tracked = v.get("inventory_management") == "shopify"
            if not tracked:
                status, note = UNKNOWN, "店铺未跟踪库存"
            else:
                status, note = (IN if v.get("available") else OUT), ""
            color = " / ".join(
                o for i, o in enumerate(v.get("options") or []) if i != size_idx and o
            )
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=h,
                    title=title,
                    url=f"https://{domain}/products/{h}?variant={v['id']}",
                    variant_id=str(v["id"]),
                    raw_size=str(raw),
                    uk=to_uk(raw, cfg.get("size_system", "AUTO"), gender),
                    color=color,
                    price=(v.get("price") or 0) / 100,
                    currency=cfg["currency"],
                    status=status,
                    condition=cond,
                    note=note,
                )
            )
    if not res.products_checked and not cfg.get("allow_empty", True):
        return StoreResult(store=sid, ok=False, error="一个商品都没找到")
    return res
