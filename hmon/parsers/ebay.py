"""eBay 官方 Browse API（免费，需要在 developer.ebay.com 注册拿 App ID 和 Cert ID）。

环境变量：EBAY_APP_ID、EBAY_CERT_ID。没有就跳过（不算失效）。
每条在售 listing 视为“有货”；从搜索结果里消失 = 下架。
"""
from __future__ import annotations

import base64
import os

import requests

from ..core import IN, Obs, StoreResult
from ..sizes import gender_from_title, to_uk

_TOKEN = {}


def _token() -> str | None:
    app, cert = os.environ.get("EBAY_APP_ID"), os.environ.get("EBAY_CERT_ID")
    if not app or not cert:
        return None
    if "t" in _TOKEN:
        return _TOKEN["t"]
    auth = base64.b64encode(f"{app}:{cert}".encode()).decode()
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=25,
    )
    r.raise_for_status()
    _TOKEN["t"] = r.json()["access_token"]
    return _TOKEN["t"]


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    try:
        tok = _token()
    except requests.RequestException as e:
        return StoreResult(store=sid, ok=False, error=f"eBay 登录失败：{e}")
    if tok is None:
        return StoreResult(store=sid, ok=True, error="未配置 eBay 密钥，已跳过")
    res = StoreResult(store=sid, ok=True)
    try:
        r = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": cfg.get("marketplace", "EBAY_US")},
            params={"q": cfg.get("search", "five ten hiangle"), "limit": 100,
                    "filter": "buyingOptions:{FIXED_PRICE}"},
            timeout=25,
        )
        r.raise_for_status()
        items = r.json().get("itemSummaries", [])
    except (requests.RequestException, ValueError) as e:
        return StoreResult(store=sid, ok=False, error=f"eBay 搜索失败：{e}")
    for it in items:
        title = it.get("title", "")
        if "hiangle" not in title.lower():
            continue
        iid = it["itemId"]
        res.products_checked.add(iid)
        cond = (it.get("condition") or "").lower()
        condition = "new" if cond.startswith("new") else "used" if cond else "unknown"
        price = it.get("price") or {}
        res.obs.append(
            Obs(
                store=sid,
                product_id=iid,
                title=title,
                url=it.get("itemWebUrl", ""),
                variant_id="1",
                raw_size=title,
                uk=to_uk(title, "AUTO", gender_from_title(title)),
                color="",
                price=float(price["value"]) if price.get("value") else None,
                currency=price.get("currency", cfg.get("currency", "USD")),
                status=IN,
                condition=condition,
                note=f"eBay 成色：{it.get('condition', '未知')}；所在地 {(it.get('itemLocation') or {}).get('country', '?')}",
            )
        )
    known = set(cfg.get("_known_products", []))
    res.gone_products = known - res.products_checked
    return res
