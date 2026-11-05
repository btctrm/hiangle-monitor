"""willhaben.at（奥地利二手市场）。

搜索页 https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=hiangle 是 Next.js，
<script id="__NEXT_DATA__"> 里 props.pageProps.searchResult.advertSummaryList.advertSummary[]，
每条 attributes.attribute[] 是 {name, values}：HEADING / BODY_DYN / PRICE / PRICE_FOR_DISPLAY / SEO_URL /
TEASER_ATTRIBUTE（"Schuhgröße 41, 42" 只是分类桶，不精确，仅作原文参考）。
有的广告标题不写型号（"Kletterschuhe adidas"），正文写 Hiangle，所以标题或正文含 hiangle 都收。
成色：搜索结果不带“Zustand”，详情页才有（每条多 1 次请求，不划算），按标题+正文关键词判断。

cfg：
  searches: [hiangle]
  rows: 90
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import condition_from_text, finish, hiangle_match, is_reserved, parse_price, size_from_text

BASE = "https://www.willhaben.at"
_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    for q in cfg.get("searches", ["hiangle"]):
        url = (f"{BASE}/iad/kaufen-und-verkaufen/marktplatz?keyword={urllib.parse.quote(q)}"
               f"&rows={int(cfg.get('rows', 90))}")
        try:
            html = fetch(url)
            m = _NEXT.search(html)
            if not m:
                raise ValueError("找不到 __NEXT_DATA__（可能改版或被拦截）")
            sr = json.loads(m.group(1))["props"]["pageProps"]["searchResult"]
            ads = (sr.get("advertSummaryList") or {}).get("advertSummary") or []
            if "rowsFound" not in sr or "advertSummaryList" not in sr:
                raise ValueError("searchResult 缺少 rowsFound/advertSummaryList（结构变了）")
            if int(sr.get("rowsFound") or 0) > 0 and not ads:
                raise ValueError("rowsFound>0 但没有 advertSummary（结构变了）")
        except (FetchError, ValueError, KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        for a in ads:
            A = {x.get("name"): (x.get("values") or [""])[0] for x in (a.get("attributes") or {}).get("attribute", [])}
            title = A.get("HEADING") or a.get("description") or ""
            body = A.get("BODY_DYN") or ""
            aid = str(a.get("id") or A.get("ADID") or "")
            ok, via_body = hiangle_match(title, body)
            if not aid or aid in res.products_checked or not ok:
                continue
            st = (a.get("advertStatus") or {}).get("id")
            status = IN if st == "active" and not is_reserved(title) else UNKNOWN
            res.products_checked.add(aid)
            raw, uk = size_from_text(title, body)
            seo = A.get("SEO_URL") or ""
            price = parse_price(A.get("PRICE") or "") if A.get("PRICE") else None
            res.obs.append(Obs(
                store=sid, product_id=aid, title=title, url=f"{BASE}/iad/{seo}" if seo else f"{BASE}/iad/object?adId={aid}",
                variant_id="1", raw_size=raw or A.get("TEASER_ATTRIBUTE", ""), uk=uk, color="",
                price=price, currency=cfg.get("currency", "EUR"), status=status,
                condition=condition_from_text(title, body),
                note=f"{A.get('LOCATION', '')}；平台分类尺码：{A.get('TEASER_ATTRIBUTE', '?')}；成色按标题/正文关键词判断"
                     + (f"；广告状态 {st}" if st != "active" else "")
                     + ("；型号仅见于正文，标题未写 Hiangle" if via_body else ""),
            ))
    return finish(res, cfg)
