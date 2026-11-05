"""Sportano（sportano.pl，Magento 2）。

发现：站内搜索 /catalogsearch/result/?q=hiangle 的商品链接（/p/<id>/<slug>），再加 cfg.urls。
逐码：商品页 Magento "spConfig" 里尺码选项 {label: "38 2/3 EU", products:[子商品id], isInStock}。
交叉验证：JSON-LD 每码一条 Offer（按 EAN，不带尺码）——只核对“有货条数”与 spConfig 一致，
不一致整页记为 UNKNOWN。价格用 spConfig optionPrices[子id].finalPrice（页面标价）；
salesRulePrice（需领码的促销价）只写进 note。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle", re.I)
_MAX_PRODUCTS = 4


def _json_after(html: str, key: str):
    """取 `"key": {...}` 后面那个 JSON 对象（花括号配平）。"""
    i = html.find(f'"{key}"')
    if i < 0:
        return None
    j = html.find("{", i)
    if j < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[j:])
        return obj
    except ValueError:
        return None


def _ld_product(html: str):
    for block in _LD.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        for it in d if isinstance(d, list) else [d]:
            if isinstance(it, dict) and it.get("@type") == "Product":
                return it
    return None


def _discover(cfg: dict) -> dict[str, str]:
    base = cfg.get("base", "https://sportano.pl").rstrip("/")
    html = fetch(f"{base}/catalogsearch/result/?q={cfg.get('search', 'hiangle')}")
    out = {}
    for pid, slug in re.findall(re.escape(base) + r'/p/(\d+)/([a-z0-9-]+)', html):
        if _HI.search(slug.replace("-", " ")) or "hiangle" in slug:
            out[pid] = f"{base}/p/{pid}/{slug}"
    return out


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    try:
        found = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    for u in cfg.get("urls", []):
        m = re.search(r"/p/(\d+)/", u)
        if m:
            found.setdefault(m.group(1), u)
    if not found:
        return StoreResult(store=sid, ok=False, error="搜索结果和配置里都没有 Hiangle 商品")

    for pid, url in sorted(found.items())[:_MAX_PRODUCTS]:
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        ld = _ld_product(html)
        sp = _json_after(html, "spConfig")
        if not ld or not sp or not sp.get("attributes"):
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到 JSON-LD 或 spConfig（可能改版）")
        title = ld.get("name", "")
        if not _HI.search(title):
            continue
        attrs = list(sp["attributes"].values())
        size_attrs = [a for a in attrs if str(a.get("code", "")).lower() in ("rozmiar", "size")]
        if len(size_attrs) != 1 or len(attrs) != 1:
            return StoreResult(store=sid, ok=False, error=f"{pid}: spConfig 属性不是单一尺码属性（{[a.get('code') for a in attrs]}）")
        options = size_attrs[0].get("options") or []
        if not options:
            return StoreResult(store=sid, ok=False, error=f"{pid}: spConfig 没有尺码选项（可能改版）")
        prices = sp.get("optionPrices") or {}
        offers = ld.get("offers") or []
        if isinstance(offers, dict):
            offers = [offers]
        ld_in = sum(1 for o in offers if str(o.get("availability", "")).endswith("/InStock"))
        sp_in = sum(1 for o in options if o.get("isInStock") is True)
        consistent = len(offers) == len(options) and ld_in == sp_in
        currency = (offers[0].get("priceCurrency") if offers else None) or cfg.get("currency", "PLN")
        gender = cfg.get("gender") or ("W" if "damsk" in url else "M" if "mesk" in url else gender_from_title(title))
        res.products_checked.add(pid)
        for o in options:
            child = (o.get("products") or [""])[0]
            raw = str(o.get("label", ""))
            pr = prices.get(child) or {}
            price = (pr.get("finalPrice") or {}).get("amount")
            rule = (pr.get("salesRulePrice") or {}).get("amount")
            if not consistent:
                status, note = UNKNOWN, f"spConfig 与 JSON-LD 有货条数不一致（{sp_in}/{ld_in}）"
            else:
                st = o.get("isInStock")
                status = IN if st is True else OUT if st is False else UNKNOWN
                note = ""
            if rule and price and rule < price:
                note = (note + "；" if note else "") + f"领券价 {rule:g} {currency}"
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=url,
                    variant_id=str(child or raw),
                    raw_size=raw,
                    uk=to_uk(raw.replace("EU", "").strip(), "EU", gender),
                    color=title.split("Hiangle", 1)[-1].strip(),
                    price=float(price) if price is not None else None,
                    currency=currency,
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
