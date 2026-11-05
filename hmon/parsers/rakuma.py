"""ラクマ / Rakuma（fril.jp，日本フリマ）。

搜索页 https://fril.jp/s?query=<q>&transaction=selling（只看出售中）是服务器渲染 HTML，每件商品的
<a class="link_search_image" href="https://item.fril.jp/<hash>" … data-rat-item_name="…" data-rat-brand="…"
data-rat-price="4000">。“ハイアングル”也指 THE NORTH FACE 的冲锋衣，所以要求品牌是 FIVE TEN/adidas
或标题带品牌/攀岩词。
命中的商品再取详情页（每轮最多 max_details 件）：JSON-LD Product.offers {price, availability, itemCondition}，
以及表格里的“商品の状態”（新品、未使用 / 未使用に近い / 目立った傷や汚れなし / やや傷や汚れあり / 傷や汚れあり /
全体的に状態が悪い）和描述（尺码在描述里，如 "us6 23cm"）。
详情页失败时整店作废（不返回半截数据）。

cfg：
  searches: [ハイアングル]
  max_details: 4
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import fix_mojibake, clean, condition_from_text, finish, is_bundle, is_hiangle, merge_condition, size_from_text

GRADE = {
    "新品、未使用": "new", "新品・未使用": "new", "未使用に近い": "like_new",
    "目立った傷や汚れなし": "used", "やや傷や汚れあり": "used", "傷や汚れあり": "used", "全体的に状態が悪い": "used",
}
_A = re.compile(r'<a href="(https://item\.fril\.jp/[0-9a-f]+)" class="link_search_image"(.*?)>', re.S)


def _detail(url: str) -> dict:
    h = fix_mojibake(fetch(url))
    prod = None
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            prod = d
    if not prod:
        raise ValueError("详情页没有 Product JSON-LD")
    g = re.search(r"商品の状態</th>\s*<td>(.*?)</td>", h, re.S)
    return {"ld": prod, "grade": clean(g.group(1)) if g else ""}


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    cands: dict[str, dict] = {}
    for q in cfg.get("searches", ["ハイアングル"]):
        url = f"https://fril.jp/s?query={urllib.parse.quote(q)}&transaction=selling"
        try:
            html = fix_mojibake(fetch(url))
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        links = _A.findall(html)
        if not links and "data-rat-cp-totalresults" not in html and "該当する商品が見つかりません" not in html:
            return StoreResult(store=sid, ok=False, error="搜索页结构不对（找不到商品链接）")
        for href, attrs in links:
            name = _html.unescape((re.search(r'data-rat-item_name="([^"]*)"', attrs) or [None, ""])[1])
            brand = _html.unescape((re.search(r'data-rat-brand="([^"]*)"', attrs) or [None, ""])[1])
            price = (re.search(r'data-rat-price="(\d+)"', attrs) or [None, ""])[1]
            if not is_hiangle(name, brand, need_brand=True) or is_bundle(name):
                continue
            if brand and not re.search(r"five\s*ten|adidas", brand, re.I):
                continue  # 例如 THE NORTH FACE ハイアングルジャケット
            pid = href.rsplit("/", 1)[1]
            cands.setdefault(pid, {"url": href, "name": name, "price": price})
    for i, (pid, c) in enumerate(cands.items()):
        res.products_checked.add(pid)
        if i >= int(cfg.get("max_details", 4)):
            res.obs.append(Obs(
                store=sid, product_id=pid, title=c["name"], url=c["url"], variant_id="1", raw_size=c["name"][:40],
                uk=None, color="", price=float(c["price"]) if c["price"] else None, currency="JPY",
                status=UNKNOWN, condition="unknown", note="本轮详情页配额用完，未核实",
            ))
            continue
        try:
            d = _detail(c["url"])
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"详情页失败：{e}")
        except ValueError as e:
            return StoreResult(store=sid, ok=False, error=str(e))
        ld = d["ld"]
        off = ld.get("offers") or {}
        desc = ld.get("description") or ""
        try:
            price = float(off.get("price"))
        except (TypeError, ValueError):
            price = float(c["price"]) if c["price"] else None
        avail = str(off.get("availability", ""))
        status = IN if avail.endswith("InStock") else OUT if avail.endswith(("OutOfStock", "SoldOut")) else UNKNOWN
        cond = merge_condition(GRADE.get(d["grade"]), condition_from_text(c["name"]))
        if d["grade"] not in GRADE:
            cond = condition_from_text(c["name"], desc)
        raw, uk = size_from_text(c["name"], desc)
        res.obs.append(Obs(
            store=sid, product_id=pid, title=clean(ld.get("name") or c["name"]), url=c["url"], variant_id="1",
            raw_size=raw or c["name"][:40], uk=uk, color="", price=price, currency=off.get("priceCurrency") or "JPY",
            status=status, condition=cond,
            note=f"平台成色：{d['grade'] or '未知'}；尺码取自标题/描述",
        ))
    return finish(res, cfg)
