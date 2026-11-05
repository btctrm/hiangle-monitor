"""에누리（Enuri，韩国比价站）。

搜索页 https://price.enuri.com/search?keyword=파이브텐 하이앵글（必须用韩文关键词，英文搜不到）
的 JSON-LD ItemList：itemListElement[].item = {name, sku, url, offers{price, priceCurrency, availability}}。
每条 = 一个店铺商品（多为 [해외] 海外代购），没有尺码数据 → 码制不明（标题里写了 mm/cm 才换算）。
1 次请求；列表里消失 = 下架。
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle|하이앵글", re.I)
_NOT_SHOE = re.compile(r"양말|가방|초크|브러시|깔창")


def _condition(t: str) -> str:
    if re.search(r"중고|used", t, re.I):
        return "used"
    if re.search(r"미사용", t):
        return "new"
    return "new"


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    kw = cfg.get("search", "파이브텐 하이앵글")
    url = "https://price.enuri.com/search?keyword=" + urllib.parse.quote(kw)
    try:
        page = fetch(url)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    items = None
    for block in _LD.findall(page):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("itemListElement"), list):
            items = [el.get("item") or {} for el in d["itemListElement"]]
            break
    if items is None:
        return StoreResult(store=sid, ok=False, error="搜索页找不到 JSON-LD ItemList（可能改版或被拦截）")
    res = StoreResult(store=sid, ok=True)
    for it in items:
        name = str(it.get("name") or "")
        if not _HI.search(name) or _NOT_SHOE.search(name):
            continue
        pid = str(it.get("sku") or it.get("url") or "")
        if not pid or pid in res.products_checked:
            continue
        res.products_checked.add(pid)
        off = it.get("offers") or {}
        if isinstance(off, list):
            off = off[0] if off else {}
        avail = str(off.get("availability", "")).rsplit("/", 1)[-1]
        status = IN if avail == "InStock" else OUT if avail in ("OutOfStock", "SoldOut", "Discontinued") else UNKNOWN
        g = "W" if re.search(r"여성|우먼|women", name, re.I) else "M" if re.search(r"남성", name) else gender_from_title(name)
        uk = to_uk(name, "AUTO", g)
        res.obs.append(
            Obs(
                store=sid,
                product_id=pid,
                title=name,
                url=str(it.get("url") or url),
                variant_id="1",
                raw_size=name if uk is not None else "（比价站未分尺码）",
                uk=uk,
                color="",
                price=float(off["price"]) if off.get("price") not in (None, "") else None,
                currency=off.get("priceCurrency") or cfg.get("currency", "KRW"),
                status=status,
                condition=_condition(name),
                note="Enuri" + ("（海外代购）" if "[해외]" in name else ""),
            )
        )
    # 结果超过一页时（JSON-LD 只有第 1 页约 38 条），没出现的旧商品可能只是排到了后面：不记下架
    mt = re.search(r'listCount\\?"\s*:\s*\{\s*\\?"total\\?"\s*:\s*(\d+)', page)
    if mt and int(mt.group(1)) <= len(items):
        for k in cfg.get("_known_products", []):
            if k not in res.products_checked:
                res.gone_products.add(k)
    return res
