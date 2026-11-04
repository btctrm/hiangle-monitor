"""日本综合电商的官方商品搜索接口（免费，需要注册拿密钥）。

日本的 ZOZOTOWN、ABC-MART、各家运动鞋店多在 Yahoo!购物 / 乐天开店，
攀岩鞋常被当成普通运动鞋一起打折、送积分，所以值得盯。

- Yahoo!ショッピング 商品検索 API v3：环境变量 YAHOO_JP_APPID（developer.yahoo.co.jp 注册应用拿 Client ID）
- 楽天市場 商品検索 API：环境变量 RAKUTEN_APP_ID，新版接口还要 RAKUTEN_ACCESS_KEY（webservice.rakuten.co.jp）
没配密钥就跳过（不算失效）。

每条在售商品记一条；日本店铺一个商品页通常包含多个尺码，接口不给逐码库存，
所以尺码一律记“码制不明”（标题里写了 UK/US 码的除外），按 ¥850 那条线判断，推送里请你自己看码。
"""
from __future__ import annotations

import os
import re

import requests

from ..core import IN, Obs, StoreResult
from ..sizes import gender_from_title, to_uk

KEYWORDS = ("hiangle", "ハイアングル", "ハイ アングル")
EXCLUDE = re.compile(r"キッズ|ジュニア|kids|junior|中古ジャンク", re.I)


def _match(title: str, cfg: dict) -> bool:
    t = title.lower()
    if not any(k in t for k in cfg.get("keywords", KEYWORDS)):
        return False
    return not EXCLUDE.search(title)


def _uk(title: str):
    return to_uk(title, "AUTO", gender_from_title(title))


def _yahoo(cfg: dict, res: StoreResult) -> str | None:
    appid = os.environ.get("YAHOO_JP_APPID")
    if not appid:
        return "未配置 YAHOO_JP_APPID，已跳过"
    r = requests.get(
        "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch",
        params={"appid": appid, "query": cfg.get("search", "ファイブテン ハイアングル"), "results": 50, "sort": "+price"},
        timeout=25,
    )
    r.raise_for_status()
    for it in r.json().get("hits", []):
        title = it.get("name", "")
        if not _match(title, cfg) or not it.get("inStock", False):
            continue
        code = str(it.get("code") or it.get("url"))
        res.products_checked.add(code)
        cond = str(it.get("condition") or "").lower()
        res.obs.append(Obs(
            store=cfg["id"], product_id=code, title=title, url=it.get("url", ""), variant_id="1",
            raw_size=title[:60], uk=_uk(title), color="", price=float(it.get("price") or 0) or None,
            currency="JPY", status=IN, condition="used" if cond == "used" else "new" if cond == "new" else "unknown",
            note=f"店铺：{(it.get('seller') or {}).get('name', '?')}；日本店一个页面多个尺码，请打开确认你要的码有货",
        ))
    return None


def _rakuten(cfg: dict, res: StoreResult) -> str | None:
    app = os.environ.get("RAKUTEN_APP_ID")
    if not app:
        return "未配置 RAKUTEN_APP_ID，已跳过"
    params = {"applicationId": app, "keyword": cfg.get("search", "ファイブテン ハイアングル"), "availability": 1,
              "hits": 30, "format": "json", "formatVersion": 2, "sort": "+itemPrice"}
    if os.environ.get("RAKUTEN_ACCESS_KEY"):
        params["accessKey"] = os.environ["RAKUTEN_ACCESS_KEY"]
    # 乐天 2025–2026 年在迁移接口地址；地址可在 config.yaml 的 endpoint 改
    url = cfg.get("endpoint", "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601")
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    for it in r.json().get("Items", []):
        it = it.get("Item", it)  # 兼容 formatVersion 1
        title = it.get("itemName", "")
        if not _match(title, cfg) or str(it.get("availability", 1)) != "1":
            continue
        code = str(it.get("itemCode") or it.get("itemUrl"))
        res.products_checked.add(code)
        res.obs.append(Obs(
            store=cfg["id"], product_id=code, title=title[:120], url=it.get("itemUrl", ""), variant_id="1",
            raw_size=title[:60], uk=_uk(title), color="", price=float(it.get("itemPrice") or 0) or None,
            currency="JPY", status=IN, condition="used" if re.search(r"中古|USED", title, re.I) else "new",
            note=f"店铺：{it.get('shopName', '?')}；日本店一个页面多个尺码，请打开确认你要的码有货",
        ))
    return None


def scan(cfg: dict) -> StoreResult:
    res = StoreResult(store=cfg["id"], ok=True)
    try:
        skipped = {"yahoo_jp": _yahoo, "rakuten": _rakuten}[cfg["api"]](cfg, res)
    except (requests.RequestException, ValueError, KeyError) as e:
        msg = str(e)
        for k in ("YAHOO_JP_APPID", "RAKUTEN_APP_ID", "RAKUTEN_ACCESS_KEY"):  # 仓库公开，日志里不能出现密钥
            if os.environ.get(k):
                msg = msg.replace(os.environ[k], "***")
        msg = re.sub(r"(appid|applicationId|accessKey)=[^&\s]+", r"\1=***", msg)
        return StoreResult(store=cfg["id"], ok=False, error=f"接口失败：{e.__class__.__name__}: {msg[:150]}")
    if skipped:
        return StoreResult(store=cfg["id"], ok=True, error=skipped)
    res.gone_products = set(cfg.get("_known_products", [])) - res.products_checked
    return res
