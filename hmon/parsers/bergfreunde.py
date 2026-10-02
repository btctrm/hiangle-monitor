"""Bergfreunde 系（bergfreunde.eu / .de / alpinetrek.co.uk 等同一平台）。

双来源交叉验证：
  1) 页面 JSON-LD 里每个尺码的 availability（InStock / OutOfStock）
  2) 页面脚本里同一 EAN 的 stockStatus.isBuyable（能否下单）
两者一致才采信；不一致记为“未知”。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_BUY = re.compile(
    r'"ean":"(\d+)"[^{}]*?"variants":\{[^{}]*\},"stockStatus":\{"bulkgood":[^,]*,'
    r'"text":"[^"]*"(?:,"raw":\{[^{}]*\})?,"isBuyable":(true|false)'
)


def _discover(cfg: dict) -> set[str]:
    base = cfg["base"].rstrip("/")
    html = fetch(f"{base}/index.php?cl=search&searchparam={cfg.get('search', 'hiangle')}")
    urls = set()
    for href in re.findall(r'href="(' + re.escape(base) + r'/[^"?#]+/)"', html):
        slug = href[len(base):].strip("/")
        if "/" in slug:
            continue
        if cfg.get("slug_must", "hiangle") in slug and slug.endswith(cfg.get("slug_suffix", "climbing-shoes")):
            urls.add(href)
    return urls


def _product_group(html: str):
    for block in _LD.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "ProductGroup":
                return it
    return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    try:
        urls = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    base = cfg["base"].rstrip("/")
    urls |= {base + "/" + u.strip("/") + "/" for u in cfg.get("paths", [])}
    urls |= {base + "/" + u + "/" for u in cfg.get("_known_products", [])}
    if not urls:
        return StoreResult(store=sid, ok=False, error="搜索结果里没有 Hiangle，可能页面改版")

    for url in sorted(urls):
        slug = url[len(base):].strip("/")
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(slug)
                continue
            return StoreResult(store=sid, ok=False, error=f"{slug}: {e}")
        pg = _product_group(html)
        if not pg or not pg.get("hasVariant"):
            return StoreResult(store=sid, ok=False, error=f"{slug}: 找不到结构化库存数据（可能改版）")
        buyable = {ean: (b == "true") for ean, b in _BUY.findall(html)}
        all_out = all(
            str((v.get("offers") or {}).get("availability", "")).endswith("OutOfStock") for v in pg["hasVariant"]
        )
        if not buyable and not all_out:
            # 有尺码声称有货，却找不到第二个来源核对：整店按未知处理
            return StoreResult(store=sid, ok=False, error=f"{slug}: 找不到下单状态数据（可能改版）")
        res.products_checked.add(slug)
        title = pg.get("name", "")
        gender = "W" if "women" in slug else gender_from_title(title) or "M"
        for v in pg["hasVariant"]:
            off = v.get("offers") or {}
            avail = str(off.get("availability", "")).rsplit("/", 1)[-1]
            ean = str(v.get("gtin") or "")
            b = buyable.get(ean)
            if avail == "InStock" and b is True:
                status, note = IN, ""
            elif avail == "OutOfStock" and (b is False or (b is None and all_out)):
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"两个来源不一致：{avail} / isBuyable={b}"
            name = v.get("name", "")
            raw = name.rsplit("|", 1)[-1].strip() if "|" in name else str(v.get("size", ""))
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=slug,
                    title=title,
                    url=url,
                    variant_id=str(v.get("sku") or ean),
                    raw_size=raw,
                    uk=to_uk(raw, cfg.get("size_system", "AUTO"), gender),
                    color=str(v.get("color", "")),
                    price=float(off["price"]) if off.get("price") is not None else None,
                    currency=off.get("priceCurrency") or cfg["currency"],
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
