"""Kijiji.ca（加拿大分类广告）。

搜索页 https://www.kijiji.ca/b-canada/<query>/k0l0 是 Next.js 服务器渲染，__NEXT_DATA__ →
props.pageProps.__APOLLO_STATE__：ROOT_QUERY["searchResultsPageByUrl:…"].results.mainListings(...) 是
[{__ref: "StandardListing:<id>"}]，对应对象有 id/title/description/url/price.amount（分）。
pagination.totalCount=0 时是正常的“无结果”。
成色：平台不给，按标题+描述关键词判断。
cfg：
  searches: [hiangle, hi angle]   # 每个关键词 1 次请求
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import clean, condition_from_text, finish, is_bundle, is_hiangle, merge_condition, size_from_text

BASE = "https://www.kijiji.ca"
# attributes.all[canonicalName=="condition"]：卖家选的平台成色
PCOND = {"new": "new", "usedlikenew": "like_new", "usedgood": "used", "usedfair": "used", "used": "used", "damaged": "used"}
_WANTED = re.compile(r"^\W*(?:wanted|wtb|looking\s+for|iso)\b", re.I)


def _attr(x: dict, name: str) -> list:
    for a in ((x.get("attributes") or {}).get("all") or []):
        if isinstance(a, dict) and a.get("canonicalName") == name:
            return a.get("canonicalValues") or []
    return []


def _listings(html: str) -> list[dict]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("找不到 __NEXT_DATA__")
    ap = json.loads(m.group(1))["props"]["pageProps"]["__APOLLO_STATE__"]
    srp = next(k for k in ap["ROOT_QUERY"] if k.startswith("searchResultsPage"))
    results = ap["ROOT_QUERY"][srp]["results"]
    out = []
    for key in results:
        if key.startswith("mainListings") or key == "topListings":
            for ref in results[key] or []:
                obj = ap.get(ref.get("__ref", "")) if isinstance(ref, dict) else None
                if obj:
                    out.append(obj)
    return out


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    seen = set()
    for q in cfg.get("searches", ["hiangle"]):
        slug = urllib.parse.quote(re.sub(r"\s+", "-", q.strip().lower()))
        try:
            html = fetch(f"{BASE}/b-canada/{slug}/k0l0")
            items = _listings(html)
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        except (ValueError, KeyError, StopIteration, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"页面结构不对：{e!r}")
        for x in items:
            pid = str(x.get("id") or "")
            title = clean(x.get("title", ""))
            desc = clean(x.get("description", ""))
            if not pid or pid in seen or not is_hiangle(title, desc) or is_bundle(title) or _WANTED.search(title):
                continue
            seen.add(pid)
            res.products_checked.add(pid)
            pr = x.get("price") or {}
            amt = pr.get("amount")
            price = amt / 100 if isinstance(amt, (int, float)) and pr.get("type", "FIXED") == "FIXED" else None
            raw, uk = size_from_text(title, desc)
            pc = (_attr(x, "condition") or [None])[0]
            cond = merge_condition(PCOND.get(pc), condition_from_text(title, desc)) if pc in PCOND else condition_from_text(title, desc)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=x.get("url") or f"{BASE}/v-view-details.html?adId={pid}",
                variant_id="1", raw_size=raw or title[:40], uk=uk, color="",
                price=price, currency=cfg.get("currency", "CAD"), status=IN,
                condition=cond,
                note=f"价格类型：{pr.get('type', '?')}；平台成色：{pc or '未填'}（未填时按标题/描述关键词）；地点：{(x.get('location') or {}).get('name', '?')}",
            ))
    return finish(res, cfg)
