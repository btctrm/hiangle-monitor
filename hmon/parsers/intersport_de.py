"""Intersport Deutschland（intersport.de，含 Marktplatz 商品）。

商品页内嵌 <script id="deci-hydration-data"> JSON：
  product.name / product.prices.price.value(.unit)
  product.dimensions[key=size].selections[] {articleId, name("42 ⅔"), available}
JSON-LD Product.offers 作为页面级核对（整体 InStock/OutOfStock）：
  页面级 OutOfStock 却有尺码 available=true → 不一致，全部记 UNKNOWN。
站内搜索是前端渲染，抓不到，靠 cfg.urls 固定商品页。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_HYD = re.compile(r'<script[^>]*id="deci-hydration-data"[^>]*>(.*?)</script>', re.S)
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle", re.I)


_SIZE_OK = re.compile(r"\d{2}(?: ?[⅓⅔]| [12]/3)?")


def _fix_mojibake(html: str) -> str:
    """服务器不声明字符集时 requests 按 latin-1 解码，"⅔" 会变成乱码；还原成 UTF-8。"""
    if "â" not in html and "Ã" not in html:
        return html
    try:
        return html.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return html


def _ld_avail(html: str) -> str:
    for block in _LD.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            off = d.get("offers") or {}
            if isinstance(off, list):
                off = off[0] if off else {}
            return str(off.get("availability", "")).rsplit("/", 1)[-1]
    return ""


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for url in cfg["urls"]:
        m = re.search(r"-(p\d+)(?:[/?#]|$)", url)
        pid = m.group(1) if m else url
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        html = _fix_mojibake(html)
        m = _HYD.search(html)
        try:
            prod = json.loads(m.group(1))["product"] if m else None
        except (ValueError, KeyError):
            prod = None
        if not prod:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到 deci-hydration-data（可能改版或被拦）")
        title = prod.get("name", "")
        if not _HI.search(title):
            return StoreResult(store=sid, ok=False, error=f"{pid}: 商品名不是 Hiangle：{title}")
        dims = {d.get("key"): d for d in prod.get("dimensions") or []}
        sizes = (dims.get("size") or {}).get("selections") or []
        if not sizes:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到尺码列表（可能改版）")
        color = next((s.get("name", "") for s in (dims.get("color") or {}).get("selections") or [] if s.get("isSelected")), "")
        pr = (prod.get("prices") or {}).get("price") or {}
        try:
            price = float(pr.get("value"))
        except (TypeError, ValueError):
            price = None
        currency = pr.get("unit") or cfg.get("currency", "EUR")
        # JSON-LD 与 product.availability 只描述“当前选中的那个尺码”（product.articleId），
        # 所以拿它们核对选中尺码的 available，而不是整页。
        ld = _ld_avail(html)
        page_st = str((prod.get("availability") or {}).get("availabilityStatus") or "")
        sel = next((s for s in sizes if s.get("articleId") == prod.get("articleId")), None)
        conflict = False
        if sel is None:
            conflict, why = True, "选中尺码不在尺码列表里"
        else:
            sa = sel.get("available")
            if ld and (ld == "InStock") != (sa is True):
                conflict, why = True, f"JSON-LD={ld} 与选中尺码 available={sa} 不一致"
            elif page_st and (page_st == "available") != (sa is True):
                conflict, why = True, f"availabilityStatus={page_st} 与选中尺码 available={sa} 不一致"
        gender = cfg.get("gender") or gender_from_title(title)
        res.products_checked.add(pid)
        for s in sizes:
            raw = str(s.get("name", ""))
            a = s.get("available")
            if conflict:
                status, note = UNKNOWN, why
            else:
                status = IN if a is True else OUT if a is False else UNKNOWN
                note = "" if s is sel else "价格取自选中尺码（各尺码不单独标价）"
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=f"{url.split('?')[0]}?articleId={s.get('articleId', '')}",
                    variant_id=str(s.get("articleId") or raw),
                    raw_size=raw,
                    uk=to_uk(raw, "EU", gender) if _SIZE_OK.fullmatch(raw.strip()) else None,
                    color=color,
                    price=price,
                    currency=currency,
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
