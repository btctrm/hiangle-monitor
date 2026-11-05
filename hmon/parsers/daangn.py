"""당근마켓 Daangn / Karrot（韩国本地二手）。

搜索页 https://www.daangn.com/kr/buy-sell/?search=<q> 会 301 到 /kr/search/buy-sell/?q=<q>（直接请求后者）。
服务器渲染（Remix），内嵌 JSON 里有 "buySellArticles":[{id(=相对 URL), href, title, content, price, status
("Ongoing"/"Reserved"/"Closed"), region.name, …}]，同页还有 JSON-LD ItemList（只有 InStock 和一律 UsedCondition，
不可靠，所以不用它的成色）。
结果按访问者地区（未登录时默认首尔一带）排序/限定，不是全国全量。
“하이앵글”也是韩国服装品牌/拍照机位，所以要求标题或描述带 파이브텐/아디다스/클라이밍 等词。
成色：按标题+描述关键词（새상품/미사용/새제품 → new；중고/사용감 → used）。尺码：标题里的 245mm / 孤立 265 = mm。
状态：Ongoing → 有货；Reserved（예약중）→ 未知；Closed → 跳过（视为下架）。
限流：连续请求几次后会返回 200 + 空 buySellArticles。“하이앵글”平时总有十几条（含非鞋），所以空列表
等 10 秒重试 1 次，仍空则本轮作废（ok=False），不误判下架。每轮最多 2 次请求，every_minutes 120。

cfg：
  searches: [하이앵글]
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

from ..core import IN, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import clean, condition_from_text, finish, fix_mojibake, is_bundle, is_hiangle, parse_price, size_from_text

BASE = "https://www.daangn.com"


def _articles(html: str) -> list[dict]:
    i = html.find('"buySellArticles":')
    if i < 0:
        raise ValueError("找不到 buySellArticles")
    s = html[i + len('"buySellArticles":'):]
    arr, _ = json.JSONDecoder().raw_decode(s)
    if not isinstance(arr, list):
        raise ValueError("buySellArticles 不是数组")
    return arr


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    seen = set()
    for q in cfg.get("searches", ["하이앵글"]):
        arts = []
        for attempt in range(2):
            try:
                html = fix_mojibake(fetch(f"{BASE}/kr/search/buy-sell/?q={urllib.parse.quote(q)}"))
                arts = _articles(html)
            except FetchError as e:
                return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
            except ValueError as e:
                return StoreResult(store=sid, ok=False, error=f"页面结构不对：{e}")
            if arts:
                break
            time.sleep(10)
        if not arts:
            # 实测：短时间连续请求后服务端会返回 200 + 空 buySellArticles（软限流），而“하이앵글”正常总有
            # 十几条（含服装/相机），所以空列表视为本轮失败，不把旧 listing 记成下架。
            return StoreResult(store=sid, ok=False, error="搜索结果为空（疑似限流，本轮作废）")
        for a in arts:
            href = a.get("href") or a.get("id") or ""
            m = re.search(r"-([0-9a-z]{8,})/?$", href)
            title = clean(a.get("title", ""))
            content = a.get("content") or ""
            if not m or not title:
                continue
            pid = m.group(1)
            if pid in seen or not is_hiangle(title, content, need_brand=True) or is_bundle(title):
                continue
            st = a.get("status")
            if st == "Closed":
                continue
            seen.add(pid)
            res.products_checked.add(pid)
            raw, uk = size_from_text(title, content, korean_mm=True)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title,
                url=href if href.startswith("http") else BASE + href, variant_id="1",
                raw_size=raw or title[:40], uk=uk, color="",
                price=parse_price(a.get("price")), currency=cfg.get("currency", "KRW"),
                status=IN if st == "Ongoing" else UNKNOWN,
                condition=condition_from_text(title, content),
                note=f"状态：{st}；成色按标题+描述关键词；地区：{(a.get('region') or {}).get('name', '?')}（多为面交）",
            ))
    return finish(res, cfg)
