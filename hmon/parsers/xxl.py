"""XXL（xxl.no 等，Next.js）。

商品页 __NEXT_DATA__ → props.pageProps.newPdpProps.initialElevateProductPageData.baseProduct.products[]：
  products[0] 是当前款（含 variants），其余是同系列其他款式（只有 code/url，没 variants）。
  variant: code(EAN) / label("8,5/42 2/3" = UK/EU) / availability[channel=ONLINE].stockNumber / price.selling.range.min.value
逐码：ONLINE stockNumber>0 → 有货，=0 → 缺货，找不到 ONLINE → 未知。
尺码：标签前半 UK、后半 EU，两者换算一致才采信，否则码制不明。
发现：cfg.styles 固定款式 + 页面里同系列款式（每轮最多 _MAX_STYLES 个）。站内搜索是前端渲染，不用。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import eu_to_uk, to_uk

_ND = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle", re.I)
_MAX_STYLES = 5


def _uk_of(label: str) -> float | None:
    parts = label.split("/", 1)
    if len(parts) != 2:
        return None
    uk = to_uk(parts[0], "UK")
    eu = eu_to_uk(parts[1].strip())
    return uk if uk is not None and uk == eu else None


def _products(html: str):
    m = _ND.search(html)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
        return d["props"]["pageProps"]["newPdpProps"]["initialElevateProductPageData"]["baseProduct"]["products"]
    except (ValueError, KeyError, TypeError):
        return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    base = cfg.get("base", "https://www.xxl.no").rstrip("/")
    res = StoreResult(store=sid, ok=True)
    queue = list(dict.fromkeys(cfg.get("styles", []) + list(cfg.get("_known_products", []))))
    seen: set[str] = set()
    fetched = 0
    while queue and fetched < _MAX_STYLES:
        code = queue.pop(0)
        if code in seen:
            continue
        seen.add(code)
        url = f"{base}/p/{code}"
        fetched += 1
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(code)
                continue
            return StoreResult(store=sid, ok=False, error=f"{code}: {e}")
        prods = _products(html)
        if not prods:
            return StoreResult(store=sid, ok=False, error=f"{code}: 找不到 __NEXT_DATA__ 商品数据（可能改版）")
        cur = next((p for p in prods if p.get("code") == code), None)
        if cur is None:
            # 款式下架后可能跳转到别的商品
            res.gone_products.add(code)
            continue
        for p in prods:
            c = p.get("code")
            if c and c not in seen and _HI.search(str(p.get("title", ""))):
                queue.append(c)
        title = str(cur.get("title", ""))
        brand = (cur.get("brand") or {}).get("name", "")
        if not _HI.search(title):
            continue
        variants = cur.get("variants") or []
        if not variants:
            return StoreResult(store=sid, ok=False, error=f"{code}: 没有尺码数据（可能改版）")
        res.products_checked.add(code)
        page_url = base + str(cur.get("url") or f"/p/{code}")
        color = str(cur.get("localizedColorName") or cur.get("baseColor") or "")
        for v in variants:
            label = str(v.get("label", ""))
            online = next((a for a in v.get("availability") or [] if a.get("channel") == "ONLINE"), None)
            try:
                n = int(online["stockNumber"]) if online and online.get("stockNumber") is not None else None
            except (TypeError, ValueError):
                n = None
            if n is None:
                status, note = UNKNOWN, "找不到网店库存"
            elif n > 0 and (cur.get("isInStockOnline") is False or cur.get("isReleased") is False):
                status, note = UNKNOWN, f"网店库存 {n} 但商品级 isInStockOnline/isReleased=False"
            else:
                status, note = (IN, f"网店库存 {n}") if n > 0 else (OUT, "")
            mn = ((v.get("price") or cur.get("price") or {}).get("selling") or {}).get("range", {}).get("min") or {}
            price = mn.get("value")
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=code,
                    title=f"{brand} {title}".strip(),
                    url=base + str(v.get("url") or "") if v.get("url") else page_url,
                    variant_id=str(v.get("code") or v.get("sizeCode") or label),
                    raw_size=label,
                    uk=_uk_of(label),
                    color=color,
                    price=float(price) if price is not None else None,
                    currency=cfg.get("currency", "NOK"),
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    if not res.products_checked and not res.gone_products:
        return StoreResult(store=sid, ok=False, error="没有检查到任何 Hiangle 款式")
    return res
