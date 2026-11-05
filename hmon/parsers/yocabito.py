"""yocabito（日本，futureshop 平台）：站内搜索发现商品 + 商品页 JSON-LD ProductGroup 逐码库存。

尺码是日本 cm（"25.5cm"），按 sizes.to_uk 的 cm 规则换算（UK = cm − 18.5，与 Goofee 对照一致）。
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s\-]?angle|ハイアングル", re.I)


def _discover(cfg: dict) -> set[str]:
    base = cfg["base"].rstrip("/")
    page = fetch(f"{base}/p/search?keyword={quote(cfg.get('search', 'hiangle'))}")
    if "fs-c-" not in page and "futureshop" not in page.lower():
        raise FetchError("搜索页结构异常")
    return set(re.findall(r'href="(/c/[A-Za-z0-9_-]+/\d{8,})"', page))


def _group(page: str):
    for block in _LD.findall(page):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        for it in d if isinstance(d, list) else [d]:
            if isinstance(it, dict) and it.get("@type") == "ProductGroup" and it.get("hasVariant"):
                return it
    return None


def scan(cfg: dict) -> StoreResult:
    sid, base = cfg["id"], cfg["base"].rstrip("/")
    res = StoreResult(store=sid, ok=True)
    try:
        paths = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    paths |= set(cfg.get("paths", [])) | set(cfg.get("_known_products", []))
    if not paths:
        return StoreResult(store=sid, ok=False, error="搜索结果为空（可能改版）")
    if len(paths) > 5:
        return StoreResult(store=sid, ok=False, error=f"候选商品过多（{len(paths)}）")
    for path in sorted(paths):
        url = base + path
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(path)
                continue
            return StoreResult(store=sid, ok=False, error=f"{path}: {e}")
        pg = _group(page)
        if not pg:
            return StoreResult(store=sid, ok=False, error=f"{path}: 找不到 JSON-LD 逐码数据（可能改版）")
        title = pg.get("name", "")
        if not _HI.search(title):
            continue
        res.products_checked.add(path)
        for v in pg["hasVariant"]:
            off = v.get("offers") or {}
            if isinstance(off, list):
                off = off[0] if off else {}
            avail = str(off.get("availability", "")).rsplit("/", 1)[-1]
            status = IN if avail == "InStock" else OUT if avail in ("OutOfStock", "SoldOut") else UNKNOWN
            raw = str(v.get("size", ""))
            norm = re.sub(r"(\d)\.0(?=\s*cm)", r"\1", raw)  # "22.0cm" -> "22cm"
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=path,
                    title=title,
                    url=url,
                    variant_id=str(v.get("sku") or v.get("productID") or raw),
                    raw_size=raw,
                    uk=to_uk(norm, "AUTO"),
                    color=str(v.get("color", "")),
                    price=float(off["price"]) if off.get("price") not in (None, "") else None,
                    currency=off.get("priceCurrency") or cfg.get("currency", "JPY"),
                    status=status,
                    condition="new",
                    note="" if status != UNKNOWN else f"availability={avail}",
                )
            )
    return res
