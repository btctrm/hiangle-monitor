"""Bazoš（捷克 bazos.cz / 斯洛伐克 bazos.sk / 波兰 bazos.pl）——站点公开 RSS。

https://www.<domain>/rss.php?humkreis=0&hledat=hiangle：<item><title>标题: 价格</title><link>…/inzerat/<id>/…</link>
<description>CDATA（图片 + 正文摘要）</description>。搜索同时匹配正文，标题常不写型号
（例："Lezečky Five Ten 5.10 veľkosť 42: 90"，正文写 Hiangle），所以标题或正文含 hiangle 都收。
价格在标题最后一个 ": " 之后（"1 500" / "Dohodou" / "V textu" → 无价格）。
成色：平台无字段，按标题+正文关键词（nové/nepoužité → new；jako nové → like_new；použité/nošené → used）。

cfg：
  domain: www.bazos.sk
  searches: [hiangle]
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from ..core import IN, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import (clean, condition_from_text, finish, hiangle_match, is_reserved, parse_price,
                             size_from_text)


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    dom = cfg.get("domain", "www.bazos.cz")
    res = StoreResult(store=sid, ok=True)
    for q in cfg.get("searches", ["hiangle"]):
        url = f"https://{dom}/rss.php?humkreis=0&hledat={urllib.parse.quote_plus(q)}"
        try:
            root = ET.fromstring(fetch(url).strip().encode("utf-8"))
            ch = root.find("channel")
            if ch is None:
                raise ValueError("RSS 里没有 channel")
        except (FetchError, ET.ParseError, ValueError) as e:
            return StoreResult(store=sid, ok=False, error=f"RSS 失败：{e}")
        for it in ch.findall("item"):
            full = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = clean(it.findtext("description") or "")
            m = re.search(r"/inzerat/(\d+)/", link)
            ok, via_body = hiangle_match(full, desc)
            if not m or not ok:
                continue
            pid = m.group(1)
            if pid in res.products_checked:
                continue
            res.products_checked.add(pid)
            title, _, ptxt = full.rpartition(": ")
            if not title:
                title, ptxt = full, ""
            price = parse_price(ptxt) if re.fullmatch(r"[\d\s.,]+", ptxt.strip() or "x") else None
            raw, uk = size_from_text(title, desc)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=link, variant_id="1",
                raw_size=raw or title[:40], uk=uk, color="",
                price=price, currency=cfg.get("currency", "CZK"), status=UNKNOWN if is_reserved(title) else IN,
                condition=condition_from_text(title, desc),
                note=f"价格原文：{ptxt or '无'}；成色按标题/正文关键词判断"
                     + ("；型号仅见于正文，标题未写 Hiangle" if via_body else ""),
            ))
    return finish(res, cfg)
