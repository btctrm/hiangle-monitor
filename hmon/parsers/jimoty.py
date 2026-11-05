"""ジモティー Jimoty（日本本地分类广告，“売ります・あげます”）。

搜索页 https://jmty.jp/all/sale?keyword=<q> 是服务器渲染 HTML。在售广告是
<li class='p-articles-list-item'>…</li>，里面有 p-item-title 的 <a href="https://jmty.jp/<pref>/sale-xxx/article-<id>">标题</a>、
p-item-most-important 的 <b>15,000円</b>、p-item-detail 的描述摘要。
页面后半有“…受付終了投稿一覧”（已结束），该标题之后的条目一律不算；标题含 [受付停止中]/【決まりました】 也跳过。
“ハイアングル”混有相机/美容椅等，所以要求标题或描述带品牌/攀岩词。
成色/尺码：平台不给，按标题+描述关键词判断。多为面交，标题里常带地区。

cfg：
  searches: [hiangle, ハイアングル]
"""
from __future__ import annotations

import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import fix_mojibake, clean, condition_from_text, finish, is_bundle, is_hiangle, parse_price, size_from_text

BASE = "https://jmty.jp"
_CLOSED_HDR = re.compile(r"受付終了投稿一覧")
_SKIP = re.compile(r"受付停止中|受付終了|決まりました|取引中|売約済|SOLD", re.I)


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    seen = set()
    for q in cfg.get("searches", ["hiangle"]):
        try:
            html = fix_mojibake(fetch(f"{BASE}/all/sale?keyword={urllib.parse.quote(q)}"))
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        if "p-articles-list" not in html:
            return StoreResult(store=sid, ok=False, error="搜索页结构不对（找不到 p-articles-list）")
        m = _CLOSED_HDR.search(html)
        active = html[: m.start()] if m else html
        blocks = re.split(r"<li class='p-articles-list-item'", active)[1:]
        if blocks and not any("p-item-title" in b for b in blocks):
            return StoreResult(store=sid, ok=False, error="列表项里找不到 p-item-title（可能改版）")
        for b in blocks:
            t = re.search(r"<div class='p-item-title'>\s*<a href=\"([^\"]+)\">(.*?)</a>", b, re.S)
            if not t:
                continue  # 求人广告等没有标题链接的块
            url, title = t.group(1), clean(t.group(2))
            am = re.search(r"/article-([0-9a-z]+)", url)
            if not am:
                continue
            pid = am.group(1)
            dm = re.search(r"<div class='p-item-detail'>(.*?)</div>", b, re.S)
            desc = clean(dm.group(1)) if dm else ""
            pm = re.search(r"p-item-most-important'>(.*?)</div>", b, re.S)
            ptxt = clean(pm.group(1)) if pm else ""
            if pid in seen or _SKIP.search(title) or is_bundle(title) or not is_hiangle(title, desc, need_brand=True):
                continue
            if not re.search(r"円", ptxt) or re.search(r"時給|月給|日給", ptxt):
                continue
            seen.add(pid)
            res.products_checked.add(pid)
            raw, uk = size_from_text(title, desc)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=url if url.startswith("http") else BASE + url,
                variant_id="1", raw_size=raw or title[:40], uk=uk, color="",
                price=parse_price(ptxt), currency=cfg.get("currency", "JPY"), status=IN,
                condition=condition_from_text(title, desc),
                note=f"成色/尺码按标题+描述摘要判断（标题可能被截断）；多为面交，地区见链接",
            ))
    return finish(res, cfg)
