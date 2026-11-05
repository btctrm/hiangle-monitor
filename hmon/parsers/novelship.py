"""Novelship（新加坡球鞋转售平台，全新鞋）——站点自己的公开 JSON 接口。

1) 款式列表：https://novelship.com/api/products/silhouette/adidas%20Five%20Ten%20Hiangle?page=1&priceOrder=&where[active:eq]=true
   → {total, results:[{id, sku, name_slug, lowest_listing_price(访问者币种；null=当前无人出售)}]}
2) 每个有在售的款：/api/products/<id>/offer-lists?where[active]=true&where[active:eq]=true&modifier[c]=4&
   modifier[has_seller_api_access]=true&modifier[f]=2&page[number]=0&page[size]=1000（参数缺一不可）
   → results[]：type=="selling" 的卖单 {size:"US 8" / "US 8W", price, local_price, currency.code, is_pre_order}。
价格单位：offer.price 是平台基准币 SGD（含平台加价，不含运费）。核对：FV4744 卖单 price=248.37，
  商品页给美国访客显示“US$ 195”= 248.37 × USD/SGD 0.782（页面内嵌汇率表 SGD rate=1）。
  卖家本币报价（local_price + currency.code，如 24069 JPY）写在 note 里。
尺码：Novelship 标 "US 8"（男/中性款美码）或 "US 8W"（女款美码）。每个尺码取最低价卖单。
is_pre_order=true 表示卖家不在手、下单后再采购，note 里注明。

cfg：
  silhouette: adidas Five Ten Hiangle
  max_products: 5     # offer-lists 请求上限
"""
from __future__ import annotations

import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

BASE = "https://novelship.com"
OFFER_Q = ("where[active]=true&where[active:eq]=true&modifier[c]=4&modifier[has_seller_api_access]=true"
           "&modifier[f]=2&page[number]=0&page[size]=1000")


def _uk(size: str, women_product: bool) -> float | None:
    m = re.fullmatch(r"\s*US\s*(\d{1,2}(?:\.5)?)\s*(W|M)?\s*", size or "", re.I)
    if not m:
        return None
    g = (m.group(2) or "").upper() or ("W" if women_product else "M")
    return to_uk(m.group(1), "US_W" if g == "W" else "US_M")


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    sil = urllib.parse.quote(cfg.get("silhouette", "adidas Five Ten Hiangle"))
    try:
        d = fetch(f"{BASE}/api/products/silhouette/{sil}?page=1&priceOrder=&where[active:eq]=true", expect_json=True)
        prods = d["results"]
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"款式列表失败：{e}")
    except (KeyError, TypeError) as e:
        return StoreResult(store=sid, ok=False, error=f"款式列表结构不对：{e!r}")
    prods = [p for p in prods if re.search(r"hiangle", p.get("name_slug", ""), re.I)]
    if not prods:
        return StoreResult(store=sid, ok=False, error="款式列表里没有 Hiangle（接口可能改了）")
    budget = int(cfg.get("max_products", 5))
    # 有在售价的优先查，超出预算的款本轮不算“已检查”（不会误判下架）
    prods.sort(key=lambda p: p.get("lowest_listing_price") is None)
    for p in prods:
        sku = p.get("sku") or str(p["id"])
        slug = p.get("name_slug", "")
        women = slug.startswith("women-")
        if p.get("lowest_listing_price") is None:
            res.products_checked.add(sku)  # 无人出售：该款所有尺码记缺货
            continue
        if budget <= 0:
            continue
        budget -= 1
        try:
            od = fetch(f"{BASE}/api/products/{p['id']}/offer-lists?{OFFER_Q}", expect_json=True)
            offers = od["results"]
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"卖单接口失败（{sku}）：{e}")
        except (KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"卖单结构不对（{sku}）：{e!r}")
        res.products_checked.add(sku)
        best: dict[str, dict] = {}
        for o in offers:
            if o.get("type") != "selling" or not isinstance(o.get("price"), (int, float)):
                continue
            size = str(o.get("size") or "").strip()
            if size not in best or o["price"] < best[size]["price"]:
                best[size] = o
        title = slug.replace("-", " ").title()
        for size, o in best.items():
            local = f"{o.get('local_price')} {(o.get('currency') or {}).get('code', '?')}"
            res.obs.append(Obs(
                store=sid, product_id=sku, title=title, url=f"{BASE}/{slug}",
                variant_id=re.sub(r"\s+", "", size), raw_size=size, uk=_uk(size, women), color=sku,
                price=round(float(o["price"]), 2), currency="SGD", status=IN, condition="new",
                note=(f"卖家报价 {local}；平台价 SGD（不含运费）"
                      + ("；预售单（卖家下单后才采购，发货慢）" if o.get("is_pre_order") else "")),
            ))
    return res
