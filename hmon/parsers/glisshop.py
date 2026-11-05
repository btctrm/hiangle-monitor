"""Glisshop（glisshop.com，法国，EUR）。

商品页内嵌 window.__change['50'] = {...}：
  rootProduct.variants.axes[technicalName=axi_afineo_size].defaultItems  尺码代码 → EU 码（如 AXI_AFINEO_SIZE_88 = 38 2/3）
  rootProduct.variants.products[]  每个 [配色, 尺码代码] 一条：webStoreStock.available + hasStock/threshold
  price.valueWithTax / currencyCode  页面售价（全尺码同价，没有逐码价格）
两个库存字段一致才采信。JSON-LD 只有一个总 offer，不用。
发现：品牌页 /marque/five-ten/ 里的 hiangle 链接 + 配置固定路径 + 已知商品。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import eu_to_uk

BASE = "https://www.glisshop.com"
_HIANGLE = re.compile(r"hi[\s-]?angle", re.I)
_LINK = re.compile(r'href="https://www\.glisshop\.com/([a-z0-9-]+/five-ten/[a-z0-9-]*hiangle[a-z0-9-]*\d+)"')


def _change_block(html: str):
    for m in re.finditer(r"window\.__change\['\w+'\]\s*=\s*", html):
        try:
            d, _ = json.JSONDecoder().raw_decode(html, m.end())
        except ValueError:
            continue
        if isinstance(d, dict) and "rootProduct" in d and "price" in d:
            return d
    return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    paths = {p.strip("/") for p in cfg.get("paths", [])} | set(cfg.get("_known_products", []))
    if cfg.get("brand_page", "/marque/five-ten/"):
        try:
            html = fetch(BASE + cfg.get("brand_page", "/marque/five-ten/"))
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"品牌页失败：{e}")
        paths |= set(_LINK.findall(html))
    if not paths:
        return StoreResult(store=sid, ok=False, error="品牌页里没有 Hiangle，可能页面改版")

    for path in sorted(paths)[: int(cfg.get("max_products", 5))]:
        url = f"{BASE}/{path}"
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(path)
                continue
            return StoreResult(store=sid, ok=False, error=f"{path}: {e}")
        d = _change_block(page)
        try:
            title = d["common"]["title"]
            variants = d["rootProduct"]["variants"]
            size_axis = next(a for a in variants["axes"] if a.get("technicalName") == "axi_afineo_size")
            codes = {it["value"]: it["title"] for it in size_axis.get("defaultItems", [])}
            price = float(d["price"]["valueWithTax"])
            currency = d["price"].get("currencyCode") or cfg.get("currency", "EUR")
        except (TypeError, KeyError, StopIteration, ValueError):
            return StoreResult(store=sid, ok=False, error=f"{path}: 找不到尺码库存数据（可能改版）")
        if not _HIANGLE.search(title):
            continue
        res.products_checked.add(path)
        for p in variants.get("products", []):
            av = p.get("axesValues") or []
            if len(av) < 2:
                continue  # 只有配色、没有尺码的父级条目
            color, code = av[0], av[1]
            raw = codes.get(code)
            web = (p.get("webStoreStock") or {}).get("available")
            has, thr = p.get("hasStock"), p.get("threshold")
            if web is True and has is True:
                status, note = IN, ""
            elif web is False and has is False:
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"webStoreStock={web} hasStock={has} threshold={thr}"
            if raw is None:
                note = (note + "；" if note else "") + f"尺码代码 {code} 无对照"
            res.obs.append(Obs(
                store=sid, product_id=path, title=f"Five Ten {title}", url=url,
                variant_id=str(p.get("id")), raw_size=f"EU {raw}" if raw else code,
                uk=eu_to_uk(raw) if raw else None, color=re.sub(r"-\d+$", "", color),
                price=price, currency=currency, status=status, condition="new", note=note,
            ))
    if not res.products_checked:
        return StoreResult(store=sid, ok=False, error="没有解析到任何 Hiangle 商品")
    return res
