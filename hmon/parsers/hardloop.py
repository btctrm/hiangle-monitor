"""Hardloop（hardloop.fr，EUR）。

商品页 <script id="__NEXT_DATA__"> → props.pageProps.fallback["…/products/<id>/color-references"]
.color_references[].variations[]，每个尺码有：
  quantity               自营仓库存（>0 = 现货，几天内发货）
  out_of_stock           2 = 不可下单（页面“Épuisé”）；1 = 允许缺货下单（由供应商发货）
  available_out_of_stock 供应商可供数量（>0 且 out_of_stock=1 时页面给出发货日期，可以下单）
  prices.price           实际售价
发现：品牌页 /marques/<id>-five-ten 里的 Hiangle 链接 + 配置里的固定商品 ID。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import eu_to_uk

_HIANGLE = re.compile(r"hi[\s-]?angle", re.I)
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _eu(raw: str) -> str:
    return re.sub(r"^(\d{2})\.([12]/3)$", r"\1 \2", raw.strip())


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    base = cfg.get("base", "https://www.hardloop.fr").rstrip("/")
    prefix = cfg.get("product_prefix", "/produit/")
    res = StoreResult(store=sid, ok=True)
    ids = {str(i) for i in cfg.get("product_ids", [])} | {str(i) for i in cfg.get("_known_products", [])}
    if cfg.get("brand_page"):
        try:
            html = fetch(base + cfg["brand_page"])
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"品牌页失败：{e}")
        ids |= set(re.findall(re.escape(prefix) + r"(\d+)-[a-z0-9-]*hi-?angle", html))
    if not ids:
        return StoreResult(store=sid, ok=False, error="没有可检查的商品")

    for pid in sorted(ids)[: int(cfg.get("max_products", 5))]:
        try:
            page = fetch(f"{base}{prefix}{pid}")
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        m = _NEXT.search(page)
        try:
            fb = json.loads(m.group(1))["props"]["pageProps"]["fallback"] if m else None
        except (ValueError, KeyError):
            fb = None
        if not fb:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到 __NEXT_DATA__（可能改版）")
        prod = next((v for k, v in fb.items() if re.search(rf"/products/{pid}$", k)), None)
        refs = next((v for k, v in fb.items() if k.endswith(f"/products/{pid}/color-references")), None)
        if not isinstance(prod, dict) or not isinstance(refs, dict) or "color_references" not in refs:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到尺码库存数据（可能改版）")
        title = prod.get("name_h1") or prod.get("name") or ""
        if not _HIANGLE.search(title) or prod.get("is_second_hand"):
            continue
        url = base + (prod.get("path") or f"{prefix}{pid}")
        res.products_checked.add(pid)
        for cr in refs["color_references"]:
            color = cr.get("color") or ""
            for va in cr.get("variations") or []:
                raw = str(va.get("name", ""))
                qty = va.get("quantity")
                oos = va.get("out_of_stock")
                aoos = va.get("available_out_of_stock") or 0
                date = va.get("delivery_start_date")
                if isinstance(qty, int) and qty > 0 and oos != 2:
                    status, note = IN, f"现货 {qty}" + (f"，预计 {date} 送达" if date else "")
                elif oos == 2:
                    status, note = OUT, ""
                elif oos == 1 and aoos > 0 and date:
                    status, note = IN, f"供应商发货，预计 {date} 送达"
                else:
                    status, note = UNKNOWN, f"quantity={qty} out_of_stock={oos} aoos={aoos}"
                price = (va.get("prices") or {}).get("price")
                res.obs.append(Obs(
                    store=sid, product_id=pid, title=title, url=url,
                    variant_id=str(va.get("reference") or va.get("id_product_attribute")),
                    raw_size=f"EU {raw}", uk=eu_to_uk(_eu(raw)), color=color,
                    price=float(price) if price not in (None, "") else None,
                    currency=cfg.get("currency", "EUR"), status=status, condition="new", note=note,
                ))
    if not res.products_checked:
        return StoreResult(store=sid, ok=False, error="没有解析到任何 Hiangle 商品")
    return res
