"""Slickdeals（美国折扣社区）搜索 RSS。

https://slickdeals.net/newsearch.php?q=hiangle&searchin=first&rss=1 → RSS 2.0，<item>: title / link / guid /
description / content:encoded / pubDate。Slickdeals 搜索是 OR 匹配（"hi angle" 会搜出 Hisense 之类），
所以只搜 "hiangle"，再按标题或正文含 hiangle 过滤（帖子标题有时是 "Five Ten Gambit ... & More"，Hiangle 在正文列表里）。
RSS 不带“已过期”标记：pubDate 在 max_age_days（默认 14 天）内记 IN，更早的记 OUT（老帖，视为过期）。
价格：标题里第一个 $ 金额（"$75/$55 first time order" 取 75），取不到或 Hiangle 只在正文时为 None。
无 pubDate → UNKNOWN。
product_id = /e/<数字> 帖子号。请求数：每个关键词 1 次（默认 1 次）。
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_HI = re.compile(r"\bhi[\s\-]?angle", re.I)
_ID = re.compile(r"/e/(\d+)")
_PRICE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    max_age = float(cfg.get("max_age_days", 14))
    now = datetime.now(timezone.utc)
    seen: set[str] = set()
    for q in cfg.get("searches", ["hiangle"]):
        url = f"https://slickdeals.net/newsearch.php?q={urllib.parse.quote_plus(q)}&searchin=first&rss=1"
        try:
            xml = fetch(url)
            root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
            ch = root.find("channel")
            if root.tag != "rss" or ch is None:
                raise ValueError("不是 RSS")
        except (FetchError, ET.ParseError, ValueError) as e:
            return StoreResult(store=sid, ok=False, error=f"RSS {q!r} 失败：{e}")
        for it in ch.findall("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or it.findtext("guid") or "").strip()
            body = (it.findtext("description") or "") + " " + (it.findtext(_CONTENT) or "")
            m = _ID.search(link)
            if not m or not (_HI.search(title) or _HI.search(body)):
                continue
            pid = m.group(1)
            if pid in seen:
                continue
            seen.add(pid)
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate") or "")
                age = (now - pub).total_seconds() / 86400
            except (TypeError, ValueError):
                pub, age = None, None
            in_title = bool(_HI.search(title))
            # Hiangle 只在正文（"Gambit ... & More" 合集帖）时标题价格属于别的鞋，不用
            pm = _PRICE.search(title) if in_title else None
            price = float(pm.group(1).replace(",", "")) if pm else None
            uk = to_uk(title, "AUTO", gender_from_title(title))
            fresh = age is not None and age <= max_age
            res.products_checked.add(pid)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=link.split("?")[0], variant_id="1",
                raw_size=title if uk is not None else "", uk=uk, color="", price=price,
                currency=cfg.get("currency", "USD"), status=(UNKNOWN if age is None else (IN if fresh else OUT)), condition="new",
                note=(f"折扣帖，发布于 {pub.date() if pub else '?'}"
                      f"{'' if fresh else f'（超过 {max_age:g} 天，视为过期）'}；价格取自标题；"
                      f"{'' if in_title else 'Hiangle 只出现在正文（价格不明）；'}尺码见帖子"),
            ))
    for k in cfg.get("_known_products", []):
        if k not in seen:
            res.gone_products.add(k)
    return res
