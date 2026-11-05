"""Mountex（匈牙利，mountex.hu，Nuxt）。

双来源：
  1) __NUXT_DATA__（devalue 扁平数组）→ pinia.productPage.masterProduct.products[].product：
     sku / name（末尾是英码，如 "... 7,5"）/ product_meret_property（欧码 "41 1/3"）/
     price（页面售价，HUF）/ stock（总库存）
  2) JSON-LD AggregateOffer.offers[] {sku, price, availability}
同一 sku 两边一致（stock>0 且 InStock / stock==0 且 OutOfStock）才采信，否则 UNKNOWN。
尺码：名称末尾英码与欧码换算一致才采信。站内搜索 404，靠 cfg.urls。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import eu_to_uk, to_uk

_NUXT = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle", re.I)
_WRAP = {"Reactive", "ShallowReactive", "Ref", "ShallowRef"}


def _devalue(arr: list):
    memo: dict[int, object] = {}

    def r(i):
        if not isinstance(i, int) or i < 0 or i >= len(arr):
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, dict):
            out: dict = {}
            memo[i] = out
            for k, x in v.items():
                out[k] = r(x)
            return out
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _WRAP:
                return r(v[1]) if len(v) > 1 else None
            if v and isinstance(v[0], str) and v[0] in ("Set", "Map", "Date", "RegExp", "BigInt", "null", "EmptyRef", "EmptyShallowRef"):
                return None
            out_l: list = []
            memo[i] = out_l
            out_l.extend(r(x) for x in v)
            return out_l
        return v

    return r(0)


def _ld_offers(html: str) -> dict[str, dict]:
    for block in _LD.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            agg = d.get("offers") or {}
            offs = agg.get("offers") if isinstance(agg, dict) else agg
            return {str(o.get("sku")): o for o in offs or [] if isinstance(o, dict)}
    return {}


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for url in cfg["urls"]:
        m = re.search(r"/termek/(\d+)/", url)
        pid = m.group(1) if m else url
        try:
            html = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        m = _NUXT.search(html)
        try:
            root = _devalue(json.loads(m.group(1))) if m else None
            mp = root["pinia"]["productPage"]["masterProduct"]
            items = [p["product"] for p in mp["products"]]
        except (ValueError, KeyError, TypeError):
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到 __NUXT_DATA__ 商品数据（可能改版）")
        title = str(mp.get("full_name") or mp.get("name") or "")
        if not _HI.search(title) or not items:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 商品名不是 Hiangle 或无尺码：{title}")
        ld = _ld_offers(html)
        if not ld:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到 JSON-LD offers（可能改版）")
        res.products_checked.add(pid)
        for it in items:
            sku = str(it.get("sku", ""))
            name = str(it.get("name", ""))
            eu = str(it.get("product_meret_property") or "")
            mm = re.search(r"\s(\d{1,2}(?:,5)?)$", name)
            uk_name = to_uk(mm.group(1), "UK") if mm else None
            uk_eu = eu_to_uk(eu) if eu else None
            uk = uk_name if uk_name is not None and uk_name == uk_eu else None
            off = ld.get(sku) or {}
            avail = str(off.get("availability", "")).rsplit("/", 1)[-1]
            stock = it.get("stock")
            if isinstance(stock, (int, float)) and stock > 0 and avail == "InStock":
                status, note = IN, f"库存 {stock:g}"
            elif stock == 0 and avail in ("OutOfStock", "SoldOut"):
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"两个来源不一致：stock={stock} / {avail or '无 JSON-LD'}"
            try:
                price = float(it.get("price") or off.get("price"))
            except (TypeError, ValueError):
                price = None
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=url,
                    variant_id=sku,
                    raw_size=f"EU {eu} / UK {mm.group(1) if mm else '?'}",
                    uk=uk,
                    color=str(it.get("product_szin_property") or ""),
                    price=price,
                    currency=cfg.get("currency", "HUF"),
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
