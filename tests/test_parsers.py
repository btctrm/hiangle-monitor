"""新解析器的离线测试（用 2026-11-04 实测页面结构的缩略版）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hmon.core import IN, OUT  # noqa: E402
from hmon.parsers import japan, jsonld, poshmark  # noqa: E402


def ld(obj):
    import json
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


def test_sportsshoes_single_offer():
    page = ld([{"@type": "Product", "name": "Five Ten Hiangle Climbing Shoes",
                "offers": {"@type": "Offer", "price": 59.99, "priceCurrency": "GBP",
                           "availability": "http://schema.org/OutOfStock"}}])
    jsonld.fetch = lambda u, **k: page
    r = jsonld.scan({"id": "ss", "urls": ["u"], "product_ids": ["fiv238"], "single_offer": True})
    assert r.ok and len(r.obs) == 1
    o = r.obs[0]
    assert (o.status, o.price, o.currency, o.uk) == (OUT, 59.99, "GBP", None)


def test_bergzeit_group_uk_sizes():
    page = ld({"@type": "ProductGroup", "name": "Hiangle Kletterschuhe", "hasVariant": [
        {"size": "UK 4,5", "color": "white", "offers": [{"availability": "http://schema.org/InStock", "price": 155.95, "priceCurrency": "EUR"}]},
        {"size": "UK 8", "color": "white", "offers": [{"availability": "http://schema.org/OutOfStock", "price": 155.95, "priceCurrency": "EUR"}]},
    ]})
    jsonld.fetch = lambda u, **k: page
    r = jsonld.scan({"id": "bz", "urls": ["u"], "product_ids": ["p"], "size_system": "AUTO"})
    assert [(o.uk, o.status) for o in r.obs] == [(4.5, IN), (8.0, OUT)]


def test_poshmark_listing():
    search = ld({"@type": "ItemList", "itemListElement": [
        {"url": "https://poshmark.com/listing/Five-Ten-Hiangle-Climbing-Shoes-Mens-Size-8-6ac9e119"},
        {"url": "https://poshmark.com/listing/Nike-Air-Max-123"}]})
    item = ld({"@type": "Product", "name": "Five Ten Hiangle Climbing Shoes Men&#x27;s Size 8", "offers": {
        "price": "39.0", "priceCurrency": "USD", "availability": "https://schema.org/InStock",
        "itemCondition": "https://schema.org/UsedCondition"}})
    poshmark.fetch = lambda u, **k: search if "search" in u else item
    r = poshmark.scan({"id": "pm", "_known_products": ["old1"]})
    assert r.ok and len(r.obs) == 1
    o = r.obs[0]
    assert (o.uk, o.price, o.condition, o.status, o.product_id) == (7.5, 39.0, "used", IN, "6ac9e119")
    assert "old1" in r.gone_products


def test_yahoo_jp(monkeypatch=None):
    import os

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"hits": [
                {"name": "adidas Five Ten ハイアングル クライミングシューズ", "price": 15840, "url": "https://x", "inStock": True,
                 "code": "a1", "condition": "new", "seller": {"name": "ZOZOTOWN"}},
                {"name": "ファイブテン ハイアングル キッズ", "price": 5000, "url": "https://y", "inStock": True, "code": "k"},
                {"name": "ファイブテン ハイアングル", "price": 9000, "url": "https://z", "inStock": False, "code": "s"},
            ]}
    os.environ["YAHOO_JP_APPID"] = "test"
    japan.requests.get = lambda *a, **k: R()
    r = japan.scan({"id": "yj", "api": "yahoo_jp", "_known_products": ["gone"]})
    os.environ.pop("YAHOO_JP_APPID")
    assert r.ok and [o.product_id for o in r.obs] == ["a1"]
    assert r.obs[0].currency == "JPY" and r.obs[0].uk is None and "gone" in r.gone_products


def test_japan_skips_without_key():
    import os
    os.environ.pop("RAKUTEN_APP_ID", None)
    r = japan.scan({"id": "rk", "api": "rakuten"})
    assert r.ok and "未配置" in r.error and not r.obs
