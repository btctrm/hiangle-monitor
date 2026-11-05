"""Achatmoinscher（法国比价站）。

搜索页 /recherche.php?q=hiangle 服务端渲染（注意：带 &fam= 会 302 到整个分类页，不要加）。
每张卡片 <div class="product">：
  <p class="product-category">N e-boutiques</p>
  <h4 class="product-name"><a href=…>标题</a> 或 <span onclick="vProd('id')">标题</span></h4>
  <p class="product-price">124,90€</p>   （最低价）
  coeur(<id>, …)                         （商品 id）
商品按尺码拆开（一张卡片 = 一个尺码），variant_id 固定 "1"；列出即视为有货，消失 = 下架。
尺码：标题里明确的 "EU 45 1/3"、末尾 " - 46"、或 "Taille 42"（≥35 只可能是 EU）；"taille 10,5"（UK/US 不明）不猜。
"""
from __future__ import annotations

import html as htmllib
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_BASE = "https://www.achatmoinscher.com"
_HI = re.compile(r"hi[\s-]?angle", re.I)
_NAME = re.compile(
    r'<h4 class="product-name">\s*<(?:a[^>]*href="([^"]+)"[^>]*|span[^>]*)>([^<]+)</(?:a|span)>\s*</h4>'
    r'\s*<p class="product-price">([^<]*)</p>'
)
_SHOPS = re.compile(r'class="product-category[^"]*">\s*(\d+) e-boutique')
_ID = re.compile(r"coeur\((\d+)")
_TOTAL = re.compile(r"(\d+) résultats?")
_EU_TAIL = re.compile(r"(?:\s-\s|,\s)((?:3[5-9]|4\d|5[0-2])(?: [12]/3)?)\s*$")


def _price(s: str) -> float | None:
    m = re.search(r"(\d[\d\s.]*,\d{2}|\d+)", s.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(1).replace(" ", "").replace(".", "").replace(",", "."))


def _size(title: str) -> tuple[str, float | None]:
    g = gender_from_title(title)
    m = re.search(r"\bEU\s*(\d{2}(?: [12]/3)?)", title)
    if m:
        return m.group(0), to_uk(m.group(0), "AUTO", g)
    m = _EU_TAIL.search(title)
    if m:
        return m.group(1), to_uk(m.group(1), "EU", g)
    m = re.search(r"taille\s*(\d{1,2}(?:,\d)?(?: [12]/3)?)", title, re.I)
    if m and 35 <= int(m.group(1)[:2].rstrip(",")) <= 52:  # 35 以上只可能是 EU 码
        return m.group(0), to_uk(m.group(1), "EU", g)
    return (m.group(0) if m else title), None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    url = f"{_BASE}/recherche.php?q={urllib.parse.quote_plus(cfg.get('search', 'hiangle'))}"
    try:
        html = fetch(url)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    cards = html.split('<div class="product">')[1:]
    m = _TOTAL.search(html)
    if not cards:
        if m and m.group(1) == "0":
            cards = []
        else:
            return StoreResult(store=sid, ok=False, error="搜索页找不到商品卡片（可能改版或被拦截）")
    res = StoreResult(store=sid, ok=True)
    parsed = 0
    for c in cards:
        nm, idm = _NAME.search(c), _ID.search(c)
        if not nm or not idm:
            continue
        parsed += 1
        title = re.sub(r"\s+", " ", htmllib.unescape(nm.group(2))).strip()
        if not _HI.search(title):
            continue
        pid = idm.group(1)
        if pid in res.products_checked:
            continue
        res.products_checked.add(pid)
        shops = _SHOPS.search(c)
        raw, uk = _size(title)
        res.obs.append(
            Obs(
                store=sid,
                product_id=pid,
                title=title,
                url=(_BASE + nm.group(1)) if nm.group(1) else url,
                variant_id="1",
                raw_size=raw,
                uk=uk,
                color="",
                price=_price(nm.group(3)),
                currency="EUR",
                status=IN,
                condition="new",
                note=f"Achatmoinscher 最低价；{shops.group(1) if shops else '?'} 家店",
            )
        )
    if cards and parsed == 0:
        return StoreResult(store=sid, ok=False, error="商品卡片结构不对（解析 0 条）")
    # 只有本页卡片全部解析成功、且结果总数 = 本页卡片数（没有第 2 页）时，才把没出现的旧商品记为下架
    complete = parsed == len(cards) and m is not None and int(m.group(1)) <= len(cards)
    if complete:
        for k in cfg.get("_known_products", []):
            if k not in res.products_checked:
                res.gone_products.add(k)
    return res
