"""Yahoo!オークション（日本拍卖/フリマ）。

搜索页 https://auctions.yahoo.co.jp/search/search?p=<q>&n=100 是服务器渲染 HTML，每件
<li class="Product"> 里有 data-auction-id / data-auction-title / data-auction-price（当前价）/
data-auction-buynowprice（一口价，0=无）以及图标 Product__icon--unused（平台“未使用”标记）。
注意 Product__icon--new 是“新着”（刚上架），不是成色。
“ハイアングル”单独搜会混进大量汽车/相机配件，所以只用 hiangle 和“ファイブテン ハイアングル”，
并要求标题同时有品牌/攀岩词。
价格：有一口价（即決）用一口价；没有一口价的纯拍卖 price=None（当前出价写进 note），避免低起拍价触发误推。
成色：平台“未使用”图标 → new（标题写近新/中古时取保守值）；否则按标题关键词。

cfg：
  searches: [hiangle, ファイブテン ハイアングル]
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import fix_mojibake, condition_from_text, finish, is_bundle, is_hiangle, merge_condition, size_from_text

BASE = "https://auctions.yahoo.co.jp"
_LI = re.compile(r'<li class="Product">(.*?)</li>\s*(?=<li class="Product">|</ul>)', re.S)


def _attr(block: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', block)
    return _html.unescape(m.group(1)).strip() if m else ""


def _num(v: str) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _next_items(html: str):
    """2026-11 起搜索页改成 Next.js：商品在 __NEXT_DATA__ 的 search.items.listing 里。返回 None = 不是这种页面。"""
    m = _NEXT.search(html)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
        lst = d["props"]["pageProps"]["initialState"]["search"]["items"]["listing"]
        items = lst["items"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    out = []
    for it in items:
        aid, title = str(it.get("auctionId") or ""), _html.unescape(str(it.get("title") or "")).strip()
        bin_ = it.get("buyNowPrice") or 0
        cond = str(it.get("itemCondition") or "").upper()
        out.append({"aid": aid, "title": title, "cur": it.get("price"), "bin": bin_ if it.get("isFixedPrice") or bin_ else 0,
                    "unused": cond == "NEW", "cond_raw": cond, "postage": "送料無料" if it.get("isFreeShipping") else "?"})
    return out


def _legacy_items(html: str):
    out = []
    for b in _LI.findall(html):
        icons = re.findall(r"Product__icon--(\w+)", b)
        postage = re.search(r'Product__postage">\s*(.*?)\s*<', b, re.S)
        out.append({"aid": _attr(b, "data-auction-id"), "title": _attr(b, "data-auction-title"),
                    "cur": _attr(b, "data-auction-price"), "bin": _attr(b, "data-auction-buynowprice"),
                    "unused": "unused" in icons, "cond_raw": "", "postage": postage.group(1) if postage else "?"})
    return out


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    seen = set()
    n_ok = n_404 = 0
    for q in cfg.get("searches", ["hiangle"]):
        url = f"{BASE}/search/search?p={urllib.parse.quote(q)}&n=100"
        try:
            html = fix_mojibake(fetch(url))
        except FetchError as e:
            if "404" in str(e):
                n_404 += 1  # 实测：0 结果时 Yahoo 返回 HTTP 404
                continue
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        n_ok += 1
        items = _next_items(html)
        if items is None:
            items = _legacy_items(html)
            if not items and "Products__items" not in html and "条件に一致する商品は見つかりません" not in html:
                return StoreResult(store=sid, ok=False, error="搜索页结构不对（找不到商品列表）")
        for b in items:
            aid, title = b["aid"], b["title"]
            if not aid or not title:
                return StoreResult(store=sid, ok=False, error="商品缺少 id/标题（可能改版）")
            if aid in seen or not is_hiangle(title, need_brand=True) or is_bundle(title):
                continue
            seen.add(aid)
            res.products_checked.add(aid)
            cur = _num(b["cur"])
            bin_ = _num(b["bin"])
            if bin_:
                price = bin_
                pnote = f"即決（一口价）¥{bin_:,.0f}" + (f"；当前价 ¥{cur:,.0f}" if cur and cur != bin_ else "")
            else:
                # 无一口价的拍卖：当前出价不是可成交价（最终价会上涨），不填价格，避免按低价误判档位/推送
                price = None
                pnote = f"拍卖中，无一口价；当前出价 ¥{cur:,.0f}（最终价会上涨，价格留空不参与档位）" if cur else "拍卖中，价格缺失"
            # 平台成色：NEW=未使用；USED10=未使用に近い；USED20 以上=有使用痕迹（20 目立った傷なし / 40 やや傷 / 60 傷 / 80 状態悪い）
            cr = b["cond_raw"]
            plat = ("new" if b["unused"] else "like_new" if cr == "USED10" else "used" if cr.startswith("USED") else None)
            cond = merge_condition(plat, condition_from_text(title))
            raw, uk = size_from_text(title)
            res.obs.append(Obs(
                store=sid, product_id=aid, title=title, url=f"{BASE}/jp/auction/{aid}", variant_id="1",
                raw_size=raw or title[:40], uk=uk, color="", price=price, currency=cfg.get("currency", "JPY"),
                status=IN, condition=cond,
                note=f"{pnote}；平台成色：{'未使用' if b['unused'] else (cr or '未标注')}；运费：{b['postage']}",
            ))
    if n_ok == 0:
        # 所有关键词都 404：分不清“全都 0 结果”还是 URL 改了，本轮作废，不把旧 listing 记成下架
        return StoreResult(store=sid, ok=False, error=f"所有搜索都返回 404（{n_404} 次）：0 结果或 URL 改版，本轮作废")
    return finish(res, cfg)
