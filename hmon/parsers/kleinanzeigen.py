"""Kleinanzeigen.de（德国二手分类广告）。

搜索页 https://www.kleinanzeigen.de/s-<query>/k0 是服务器渲染 HTML，每条广告是
<article ... data-adid="…" data-href="/s-anzeige/…">，里面有 <h3><a>标题</a></h3>、
<p class="…text-onSurfaceSubdued">描述摘要</p>、<p class="…font-strong…">价格（"80 € VB"）</p>。
（每条广告还有一个 ImageObject JSON-LD，只有标题/描述，不含价格，所以价格从 HTML 取。）
0 结果时页面写“Es wurden leider keine Ergebnisse…”。
成色：平台搜索页不给，按标题+描述关键词判断（neu/OVP/ungetragen → new；wie neu → like_new；
getragen/gebraucht/besohlt → used；否则 unknown）。

cfg：
  searches: [hiangle]       # 每个关键词 1 次请求（只搜 Angebote，不含 Gesuche）
"""
from __future__ import annotations

import re
import urllib.parse

from ..core import IN, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import (clean, condition_from_text, finish, hiangle_match, is_reserved, parse_price,
                             size_from_text)

BASE = "https://www.kleinanzeigen.de"
_ART = re.compile(r"<article\b([^>]*data-adid=\"\d+\"[^>]*)>(.*?)</article>", re.S)


def _parse(html: str) -> list[dict]:
    out = []
    for attrs, body in _ART.findall(html):
        adid = re.search(r'data-adid="(\d+)"', attrs).group(1)
        href = re.search(r'data-href="([^"]+)"', attrs)
        tm = re.search(r"<h2[^>]*>.*?<a[^>]*>(.*?)</a>|<h3[^>]*>.*?<a[^>]*>(.*?)</a>", body, re.S)
        title = clean((tm.group(1) or tm.group(2)) if tm else "")
        dm = re.search(r'<p class="[^"]*text-onSurfaceSubdued[^"]*">(.*?)</p>', body, re.S)
        pm = re.search(r'<p class="[^"]*font-strong[^"]*">(.*?)</p>', body, re.S)
        out.append({
            "id": adid,
            "title": title,
            "desc": clean(dm.group(1)) if dm else "",
            "price_txt": clean(pm.group(1)) if pm else "",
            "url": BASE + href.group(1) if href else f"{BASE}/s-anzeige/{adid}",
        })
    return out


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    seen = set()
    for q in cfg.get("searches", ["hiangle"]):
        # s-anzeige:angebote = 只要“Angebote”（在售），排除 Gesuche（求购）
        url = f"{BASE}/s-anzeige:angebote/{urllib.parse.quote(q.replace(' ', '-'))}/k0"
        try:
            html = fetch(url)
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        ads = _parse(html)
        if not ads and "srchrslt-adtable" not in html and "keine Ergebnisse" not in html:
            return StoreResult(store=sid, ok=False, error="搜索页结构不对（找不到结果列表）")
        if "srchrslt-adtable" in html and not ads and "keine Ergebnisse" not in html:
            return StoreResult(store=sid, ok=False, error="有结果列表但解析不出广告（可能改版）")
        for a in ads:
            ok, via_body = hiangle_match(a["title"], a["desc"])
            if a["id"] in seen or not ok:
                continue
            seen.add(a["id"])
            res.products_checked.add(a["id"])
            raw, uk = size_from_text(a["title"], a["desc"])
            res.obs.append(Obs(
                store=sid, product_id=a["id"], title=a["title"], url=a["url"], variant_id="1",
                raw_size=raw or a["title"][:40], uk=uk, color="",
                price=parse_price(a["price_txt"]), currency=cfg.get("currency", "EUR"),
                status=UNKNOWN if is_reserved(a["title"], a["price_txt"]) else IN,
                condition=condition_from_text(a["title"], a["desc"]),
                note=f"价格原文：{a['price_txt'] or '无'}；成色按标题/描述关键词判断"
                     + ("；型号仅见于描述，标题未写 Hiangle" if via_body else ""),
            ))
    return finish(res, cfg)
