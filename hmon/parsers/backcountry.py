"""Backcountry（美国）：站内搜索发现商品页 + 商品页双来源交叉验证。

  1) JSON-LD ProductGroup.hasVariant：每个在售尺码一条 offer（availability）。缺货尺码不会列出。
  2) 页面内嵌的 SKU 表 "<SKU>":{"color":…,"size":{"name","scale"},"salePrice","inventory",…}
两者一致才采信：LD=InStock 且 inventory>0 → 有货；SKU 表 inventory==0 → 缺货；不一致 → 未知。
LD 和 SKU 表都没出现的尺码由主程序按“消失=缺货”处理（products_checked）。
"""
from __future__ import annotations

import html as htmllib
import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

BASE = "https://www.backcountry.com"
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_SKU = re.compile(r'"([A-Z0-9]+-[A-Z0-9]+-S\d+)":\{"color"')
_HI = re.compile(r"hi-?angle", re.I)


def _discover(cfg: dict) -> set[str]:
    page = fetch(f"{BASE}/search?q={cfg.get('search', 'hiangle')}")
    paths = set(re.findall(r'["\'](/[a-z0-9-]*hi-?angle[a-z0-9-]*)["\'?#]', page))
    if not paths and "backcountry" not in page.lower():
        raise FetchError("搜索页结构异常")
    return {p.strip("/") for p in paths if not p.startswith("/search")}


def _group(page: str):
    for block in _LD.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for it in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(it, dict) and it.get("@type") == "ProductGroup":
                return it
    return None


def _sku_table(page: str) -> dict:
    dec, out = json.JSONDecoder(), {}
    for m in _SKU.finditer(page):
        try:
            obj, _ = dec.raw_decode(page, m.end() - len('{"color"'))
        except ValueError:
            continue
        if isinstance(obj, dict) and "inventory" in obj:
            out.setdefault(m.group(1), obj)
    return out


def _uk(size_name: str, scale: str) -> float | None:
    s = htmllib.unescape(size_name)
    m = re.search(r"Men'?s\s*([\d.]+)", s, re.I)
    if m:
        num, sys_ = m.group(1), "US_M"
    elif re.fullmatch(r"[\d.]+", s.strip()):
        sc = scale.lower()
        num = s.strip()
        sys_ = "US_W" if "women" in sc and "men's and" not in sc else "US_M" if "men" in sc else None
        if sys_ is None:
            return None
    else:
        return None
    num = re.sub(r"\.0$", "", num)
    return to_uk(num, sys_)


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    try:
        slugs = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    slugs |= set(cfg.get("paths", [])) | set(cfg.get("_known_products", []))
    if not slugs:
        return StoreResult(store=sid, ok=False, error="搜索结果里没有 Hiangle（可能改版）")
    if len(slugs) > 5:
        return StoreResult(store=sid, ok=False, error=f"候选商品过多（{len(slugs)}）")

    for slug in sorted(slugs):
        url = f"{BASE}/{slug}"
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(slug)
                continue
            return StoreResult(store=sid, ok=False, error=f"{slug}: {e}")
        pg = _group(page)
        if not pg:
            return StoreResult(store=sid, ok=False, error=f"{slug}: 找不到 JSON-LD 商品数据（可能改版或被拦截）")
        title = htmllib.unescape(pg.get("name", ""))
        if not _HI.search(title):
            continue
        style = str(pg.get("sku") or "")
        if not style:
            return StoreResult(store=sid, ok=False, error=f"{slug}: JSON-LD 缺少款号 sku（可能改版）")
        # 只要本款号的 SKU，排除推荐商品
        table = {k: v for k, v in _sku_table(page).items() if k.startswith(style + "-")}
        if not table:
            return StoreResult(store=sid, ok=False, error=f"{slug}: 找不到 SKU 库存表（可能改版）")
        res.products_checked.add(slug)
        ld = {}
        for v in pg.get("hasVariant") or []:
            off = v.get("offers") or {}
            if isinstance(off, list):
                off = off[0] if off else {}
            if str(v.get("sku", "")).startswith(style + "-"):
                ld[str(v.get("sku"))] = (v, off)
        for sku in sorted(set(ld) | set(table)):
            t = table.get(sku)
            v, off = ld.get(sku, ({}, {}))
            avail = str(off.get("availability", "")).rsplit("/", 1)[-1] if off else ""
            inv = t.get("inventory") if t else None
            if avail == "InStock" and isinstance(inv, int) and inv > 0:
                status, note = IN, f"库存 {inv}"
            elif t is not None and inv == 0 and avail != "InStock":
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"两个来源不一致：LD={avail or '无'} / inventory={inv}"
            size = (t or {}).get("size") or {}
            raw = htmllib.unescape(str(size.get("name") or v.get("size") or ""))
            color = htmllib.unescape(str(((t or {}).get("color") or {}).get("name") or v.get("color") or ""))
            price = off.get("price") if off.get("price") is not None else (t or {}).get("salePrice")
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=slug,
                    title=title,
                    url=url,
                    variant_id=sku,
                    raw_size=raw,
                    uk=_uk(raw, str(size.get("scale", ""))),
                    color=color,
                    price=float(price) if price is not None else None,
                    currency=off.get("priceCurrency") or cfg.get("currency", "USD"),
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
