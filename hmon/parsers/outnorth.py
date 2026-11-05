"""Outnorth（outnorth.com，瑞典站 SEK）。

搜索页 /se/sok?q=hiangle 找商品链接（以 -FSxxxxxx 结尾）；商品页内嵌 "variants":[...]，
每个尺码有 isBuyable、stockStatus、inventoryQuantity、price.current.inclVat、variantSpecifications.Storlek。
isBuyable 与 stockStatus 两个字段一致才采信。

尺码：新款是 Five Ten 官方 1/3 码（38 2/3 …），老款 Hiangle 用 39.5 / 41.5 这类半码。
同一商品里只要出现非官方码，整款的码制就不确定（整数码也可能不是同一张表），全部记“码制不明”。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import eu_to_uk

BASE = "https://www.outnorth.com"
_LINK = re.compile(r'href="(/se/[^"?#]*hiangle[^"?#]*-(FS\d+))"', re.I)
_HIANGLE = re.compile(r"hi[\s-]?angle", re.I)
_IN_STATUS = {"inStock", "lowStock"}
_OUT_STATUS = {"outOfStock", "phaseOut", "soldOut"}


def _unescape(s: str) -> str:
    s = s.replace("\\'", "'")
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def _variants(html: str):
    i = html.find('"variants":[{"ticket"')
    if i < 0:
        i = html.find('"variants":[{')
    if i < 0:
        return None
    try:
        v, _ = json.JSONDecoder().raw_decode(html, i + len('"variants":'))
    except ValueError:
        return None
    return v if isinstance(v, list) else None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    links: dict[str, str] = {}
    for p in cfg.get("paths", []):
        m = re.search(r"-(FS\d+)$", p.strip("/"))
        if m:
            links[m.group(1)] = "/" + p.strip("/")
    try:
        html = fetch(f"{BASE}/se/sok?q={cfg.get('search', 'hiangle')}")
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    found = {code: path for path, code in _LINK.findall(html)}
    if not found and not links:
        return StoreResult(store=sid, ok=False, error="搜索结果里没有 Hiangle，可能页面改版")
    links.update(found)

    for code, path in sorted(links.items())[: int(cfg.get("max_products", 5))]:
        url = BASE + path
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(code)
                continue
            return StoreResult(store=sid, ok=False, error=f"{path}: {e}")
        m = re.search(r'"displayName":"((?:[^"\\]|\\.)*)"', page)
        title = _unescape(m.group(1)) if m else ""
        if not _HIANGLE.search(title):
            continue
        variants = _variants(page)
        if not variants:
            return StoreResult(store=sid, ok=False, error=f"{path}: 找不到内嵌尺码数据（可能改版）")
        cur = re.search(r'"priceCurrency":"([A-Z]{3})"', page)
        currency = cur.group(1) if cur else cfg.get("currency", "SEK")
        raws = [str((v.get("variantSpecifications") or {}).get("Storlek", "")) for v in variants]
        official = all(eu_to_uk(r) is not None for r in raws)
        color = title.split("Hiangle", 1)[-1].replace("Pro", "").replace("Climbing Shoes", "").strip(" -")
        res.products_checked.add(code)
        for v, raw in zip(variants, raws):
            buy, st = v.get("isBuyable"), v.get("stockStatus")
            if buy is True and st in _IN_STATUS:
                status, note = IN, f"库存 {v.get('inventoryQuantity')}"
            elif buy is False and st in _OUT_STATUS:
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"isBuyable={buy} stockStatus={st}"
            if not official:
                note = (note + "；" if note else "") + "老款半码码制，不换算"
            price = ((v.get("price") or {}).get("current") or {}).get("inclVat")
            res.obs.append(Obs(
                store=sid, product_id=code, title=title, url=url,
                variant_id=str(v.get("articleNumber") or raw), raw_size=f"EU {raw}",
                uk=eu_to_uk(raw) if official else None, color=color,
                price=float(price) if price is not None else None, currency=currency,
                status=status, condition="new", note=note,
            ))
    if not res.products_checked:
        return StoreResult(store=sid, ok=False, error="没有解析到任何 Hiangle 商品")
    return res
