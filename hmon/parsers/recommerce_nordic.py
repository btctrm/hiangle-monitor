"""北欧 Vend/Schibsted “recommerce” 平台：finn.no / tori.fi / dba.dk / blocket.se（同一套前端）。

搜索页 https://<domain>/recommerce/forsale/search?q=hiangle 里有
<script type="application/ld+json" id="seoStructuredData">：CollectionPage.mainEntity.itemListElement[].item
= {name, url, offers.{price, priceCurrency}}。0 结果时这个 script 是空的。
注意：JSON-LD 的 itemCondition 永远是 UsedCondition（实测 "Nyskick"/全新广告也是），不可信。
真实成色只在详情页内嵌 JSON：{"name":"condition","label":"Tilstand|Kunto|Skick|Stand","value":"…","valueId":N}
实测 valueId：1=全新（Helt ny / Nytt skick - helt ny），2=近新（Som ny / Mycket bra skick - som ny），
3/4/5=有使用痕迹。所以对 Hiangle 广告逐条抓详情页（每轮最多 max_details 条，其余按标题关键词，判断不了就 unknown）。

cfg：
  domain: www.finn.no
  search: hiangle
  max_details: 4          # 搜索 1 次 + 详情 ≤4 次
"""
from __future__ import annotations

import json
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import (clean, condition_from_text, finish, is_hiangle, is_wanted, merge_condition,
                             parse_price, size_from_text)

_SEO = re.compile(r'<script[^>]*id="seoStructuredData"[^>]*>(.*?)</script>', re.S)
_COND = re.compile(
    r'"(?:id|name)\\?"\s*:\s*\\?"condition\\?"\s*,\s*\\?"label\\?"\s*:\s*\\?"([^"\\]*)\\?"\s*,\s*'
    r'\\?"value\\?"\s*:\s*\\?"([^"\\]*)\\?"\s*,\s*\\?"valueId\\?"\s*:\s*(\d+)'
)
_DESC = re.compile(r'<meta property="og:description" content="([^"]*)"')
_COND_ID = {"1": "new", "2": "like_new", "3": "used", "4": "used", "5": "used"}


_DISPOSED = re.compile(r'\\?"disposed\\?"\s*:\s*true')


def _detail(url: str) -> tuple[str | None, str, str, bool]:
    """返回 (成色, 平台成色原文, 描述, 已售出)；抓不到成色返回 (None, '', 描述, 已售出)。"""
    html = fetch(url)
    m = _COND.search(html)
    d = _DESC.search(html)
    desc = clean(d.group(1)) if d else ""
    sold = bool(_DISPOSED.search(html))
    if not m:
        return None, "", desc, sold
    return _COND_ID.get(m.group(3), "unknown"), f"{m.group(1)}: {m.group(2)}", desc, sold


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    base = "https://" + cfg["domain"]
    q = cfg.get("search", "hiangle")
    try:
        html = fetch(f"{base}/recommerce/forsale/search?q={urllib.parse.quote(q)}")
        m = _SEO.search(html)
        if not m:
            raise ValueError("找不到 seoStructuredData（可能改版或被拦截）")
        raw = m.group(1).strip()
        items = []
        if raw:
            d = json.loads(raw)
            items = [e.get("item") or {} for e in (d.get("mainEntity") or {}).get("itemListElement", [])]
    except (FetchError, ValueError, KeyError, AttributeError) as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")

    res = StoreResult(store=sid, ok=True)
    budget = int(cfg.get("max_details", 4))
    for it in items:
        name = clean(it.get("name") or "")
        desc = clean(it.get("description") or "")
        url = it.get("url") or ""
        pm = re.search(r"/item/(\d+)", url)
        if not pm or not is_hiangle(name) or is_wanted(name):
            continue
        pid = pm.group(1)
        if pid in res.products_checked:
            continue
        res.products_checked.add(pid)
        offers = it.get("offers") or {}
        plat, plat_txt, ddesc, sold = None, "", "", False
        if budget > 0:
            budget -= 1
            try:
                plat, plat_txt, ddesc, sold = _detail(url)
                plat_txt = plat_txt or "详情页没有成色字段，按标题/描述关键词"
            except FetchError:
                plat_txt = "详情页抓取失败，按标题关键词"
        if sold:  # 详情页 disposed=true：已售出，不出 obs（products_checked 里有 → 记为缺货）
            continue
        cond = merge_condition(plat, condition_from_text(name, ddesc))
        rs, uk = size_from_text(name, ddesc)
        res.obs.append(Obs(
            store=sid, product_id=pid, title=name, url=url, variant_id="1",
            raw_size=rs or name[:40], uk=uk, color="",
            price=parse_price(str(offers.get("price", ""))) if offers.get("price") not in (None, "") else None,
            currency=offers.get("priceCurrency") or cfg.get("currency", "EUR"),
            status=IN, condition=cond,
            note=f"平台成色：{plat_txt or '未取（超出每轮详情页上限，按标题关键词）'}",
        ))
    return finish(res, cfg)
