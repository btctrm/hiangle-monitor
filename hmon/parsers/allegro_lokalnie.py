"""Allegro Lokalnie（波兰二手）。

搜索页 https://allegrolokalnie.pl/oferty/q/<query> 有 JSON-LD ItemList：
itemListElement[].item = {name, url, offers.{price, priceCurrency}, itemCondition}。
itemCondition 实测会区分 NewCondition / UsedCondition，按平台字段，再用标题关键词细分“近新”。
0 结果时没有 ItemList，页面上 <span class="mlc-listing__offer-count__number">0</span>。
只有标题可用（列表无描述），只收标题含 hiangle 的。

cfg：
  searches: [hiangle, five ten wspinaczkowe]
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import clean, condition_from_text, finish, is_hiangle, is_wanted, merge_condition, size_from_text

BASE = "https://allegrolokalnie.pl"
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_COUNT = re.compile(r'offer-count__number">\s*([\d\s]+)\s*<')
_COND = {"NewCondition": "new", "UsedCondition": "used", "RefurbishedCondition": "used", "DamagedCondition": "used"}


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for q in cfg.get("searches", ["hiangle"]):
        try:
            html = fetch(f"{BASE}/oferty/q/{urllib.parse.quote(q)}")
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        items = None
        for m in _LD.findall(html):
            try:
                d = json.loads(m)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("@type") == "ItemList":
                items = [e.get("item") or {} for e in d.get("itemListElement", [])]
        cm = _COUNT.search(html)
        if items is None:
            if cm and cm.group(1).strip() == "0":
                items = []
            else:
                return StoreResult(store=sid, ok=False, error="找不到 ItemList JSON-LD 也不是 0 结果页（可能改版或被拦截）")
        for it in items:
            name = clean(it.get("name") or "")
            url = it.get("url") or ""
            pm = re.search(r"/oferta/([^/?#]+)", url)
            if not pm or not is_hiangle(name) or is_wanted(name):
                continue
            pid = pm.group(1)
            if pid in res.products_checked:
                continue
            res.products_checked.add(pid)
            offers = it.get("offers") or {}
            ctype = (it.get("itemCondition") or offers.get("itemCondition") or "").rsplit("/", 1)[-1]
            raw, uk = size_from_text(name)
            try:
                price = float(offers.get("price")) if offers.get("price") not in (None, "") else None
            except (TypeError, ValueError):
                price = None
            res.obs.append(Obs(
                store=sid, product_id=pid, title=name, url=url, variant_id="1",
                raw_size=raw or name[:40], uk=uk, color="",
                price=price, currency=offers.get("priceCurrency") or cfg.get("currency", "PLN"), status=IN,
                condition=merge_condition(_COND.get(ctype), condition_from_text(name)),
                note=f"平台成色：{ctype or '无'}",
            ))
    return finish(res, cfg)
