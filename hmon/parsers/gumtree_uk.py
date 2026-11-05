"""Gumtree UK（英国二手分类广告）。

搜索页 https://www.gumtree.com/search?search_category=all&q=<query>（必须用 q；search_query 会被忽略）。
JSON-LD SearchResultsPage.mainEntity（ItemList）只有 URL，所以用服务器渲染的卡片：
<div data-q="search-result"> 里 data-q="search-result-anchor" href=/p/<cat>/<slug>/<id>、
data-q="tile-title"、data-q="tile-price"、data-q="tile-description"、data-q="tile-location"。
"hiangle" 目前 0 结果，另外查一个更宽的关键词（five ten climbing shoes），只收标题/描述含 hiangle 的。
成色：卡片无字段，按标题+描述关键词。

cfg：
  searches: [hiangle, five ten climbing shoes]
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import clean, condition_from_text, finish, hiangle_match, parse_price, size_from_text

BASE = "https://www.gumtree.com"
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)


def _field(block: str, key: str) -> str:
    m = re.search(r'data-q="%s"[^>]*>(.*?)</(?:h2|div|p)>' % key, block, re.S)
    if not m:
        return ""
    return clean(re.sub(r"<style.*?</style>", "", m.group(1), flags=re.S))


def _n_items(html: str) -> int | None:
    for m in _LD.findall(html):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "SearchResultsPage":
            return int((d.get("mainEntity") or {}).get("numberOfItems") or 0)
    return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for q in cfg.get("searches", ["hiangle"]):
        try:
            html = fetch(f"{BASE}/search?search_category=all&q={urllib.parse.quote_plus(q)}")
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        n = _n_items(html)
        blocks = html.split('data-q="search-result"')[1:]
        if n is None:
            return StoreResult(store=sid, ok=False, error="找不到 SearchResultsPage JSON-LD（可能改版或被拦截）")
        if n > 0 and not blocks:
            return StoreResult(store=sid, ok=False, error="JSON-LD 说有结果但解析不出卡片（可能改版）")
        for b in blocks:
            hm = re.search(r'href="(/p/[^"]+?/(\d+))"', b[:800])
            if not hm:
                continue
            pid = hm.group(2)
            title = _field(b, "tile-title")
            desc = _field(b, "tile-description")
            ok, via_body = hiangle_match(title, desc)
            if pid in res.products_checked or not ok:
                continue
            res.products_checked.add(pid)
            ptxt = _field(b, "tile-price")
            raw, uk = size_from_text(title, desc)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=BASE + hm.group(1), variant_id="1",
                raw_size=raw or title[:40], uk=uk, color="",
                price=parse_price(ptxt), currency=cfg.get("currency", "GBP"), status=IN,
                condition=condition_from_text(title, desc),
                note=f"{_field(b, 'tile-location')}；成色按标题/描述关键词判断"
                     + ("；型号仅见于描述，标题未写 Hiangle" if via_body else ""),
            ))
    return finish(res, cfg)
