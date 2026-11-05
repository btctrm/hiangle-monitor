"""SidelineSwap（美国运动装备二手市场）。

搜索页 https://sidelineswap.com/search?q=hiangle 是 Next.js，__NEXT_DATA__ → props.pageProps：
  items[]：id, name, price, state ("available"), url；paging.total_count。
成色：搜索结果不给（quality_detail 多为 null），按标题关键词判断（"Used …" / "… NEW"）。
cfg：
  searches: [hiangle]
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, OUT, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import clean, condition_from_text, finish, is_bundle, is_hiangle, size_from_text

BASE = "https://sidelineswap.com"


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    seen = set()
    for q in cfg.get("searches", ["hiangle"]):
        try:
            html = fetch(f"{BASE}/search?q={urllib.parse.quote(q)}")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                raise ValueError("找不到 __NEXT_DATA__")
            pp = json.loads(m.group(1))["props"]["pageProps"]
            items = pp["items"]
            pp["paging"]["total_count"]
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        except (ValueError, KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"页面结构不对：{e!r}")
        for x in items:
            pid = str(x.get("id") or "")
            title = clean(x.get("name", ""))
            if not pid or pid in seen or not is_hiangle(title) or is_bundle(title):
                continue
            seen.add(pid)
            res.products_checked.add(pid)
            raw, uk = size_from_text(title)
            price = x.get("price")
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=x.get("url") or f"{BASE}/gear/{pid}",
                variant_id="1", raw_size=raw or title[:40], uk=uk, color="",
                price=float(price) if isinstance(price, (int, float)) else None,
                currency=cfg.get("currency", "USD"),
                status=IN if x.get("state") == "available" else OUT,
                condition=condition_from_text(title),
                note="成色按标题关键词判断",
            ))
    return finish(res, cfg)
