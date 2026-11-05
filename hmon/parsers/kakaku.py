"""価格.com（kakaku.com，日本比价站）。

搜索页 https://search.kakaku.com/<q>/?page=N（Shift_JIS，服务端渲染，每页 40 条）。
每条 <div class="c-list1_cell p-resultItem …">：
  img.p-item_visual_entity 的 alt = 完整商品名（p-item_name 里的会被截断成 "..."）
  em.p-item_priceNum = 价格（日元）；p-resultItem_quote = 店铺名；跳转链接里的 pid= = 店铺商品 id
一条 = 一个店铺商品（variant_id "1"）；列出即视为在售，消失 = 下架。
尺码从商品名解析："サイズ US_8(25.0cm)" "26.0CM" 等；男女不明的美码不猜。
"""
from __future__ import annotations

import html as htmllib
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

_HI = re.compile(r"hi[\s-]?angle|ハイアングル", re.I)
_TOTAL = re.compile(r"([\d,]+)</span>件")


def _gender(t: str) -> str | None:
    w = bool(re.search(r"\(WMNS\)|レディース|レディス|women", t, re.I))
    m = bool(re.search(r"メンズ|\bmen'?s\b", t, re.I))
    if w == m or re.search(r"ユニセックス|unisex", t, re.I):
        return None  # 都有/都没有/男女通用：不判断
    return "W" if w else "M"


def _size(title: str) -> tuple[str, float | None]:
    t = re.sub(r"US_M_", "US M ", title)
    t = re.sub(r"US_W_", "US W ", t)
    t = t.replace("US_", "US ")
    t = re.sub(r"(\d{2}(?:\.5)?)(?:\.0)?\s*(?:cm|CM|ｃｍ)", r"\1cm", t)
    m = re.search(r"サイズ\s*[^【】]{1,30}", t) or re.search(r"\d{2}(?:\.5)?cm", t)
    raw = m.group(0).strip() if m else ""
    if not raw:
        return "", None
    g = _gender(title)
    uk = None
    mc = re.search(r"(\d{2}(?:\.5)?)cm", t)
    if mc:  # 日本 cm 码最直接
        uk = to_uk(mc.group(0), "AUTO", g)
    if uk is None:
        uk = to_uk(t, "AUTO", g)
    return raw, uk


def _condition(t: str) -> str:
    if re.search(r"未使用に近い|ほぼ未使用", t):
        return "like_new"
    if re.search(r"中古|USED", t, re.I):
        return "used"
    return "new"


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    q = urllib.parse.quote(cfg.get("search", "hiangle"))
    pages = int(cfg.get("max_pages", 3))
    res = StoreResult(store=sid, ok=True)
    total = None
    seen = 0
    for page in range(1, pages + 1):
        url = f"https://search.kakaku.com/{q}/" + (f"?page={page}" if page > 1 else "")
        try:
            html = fetch(url)
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        blocks = html.split('<div class="c-list1_cell p-resultItem')[1:]
        if page == 1:
            m = _TOTAL.search(html)
            total = int(m.group(1).replace(",", "")) if m else None
            if not blocks and total != 0:
                return StoreResult(store=sid, ok=False, error="搜索页找不到结果（可能改版或被拦截）")
        if not blocks:
            break
        seen += len(blocks)
        for b in blocks:
            alt = re.search(r'alt="([^"]*)" class="p-item_visual_entity"', b)
            nm = re.search(r'<p class="p-item_name">\s*<a [^>]*>(.*?)</a>', b, re.S)
            title = htmllib.unescape(alt.group(1) if alt else re.sub(r"<[^>]+>", "", nm.group(1)) if nm else "").strip()
            pr = re.search(r'p-item_priceNum">([\d,]+)<', b)
            pidm = re.search(r"pid=([^&\"]+)", b)
            if not title or not pr or not pidm:
                continue
            if not _HI.search(title):
                continue
            pid = urllib.parse.unquote(pidm.group(1))
            if pid in res.products_checked:
                continue
            res.products_checked.add(pid)
            shop = re.search(r'p-resultItem_quote">\s*(?:<img[^>]*>)?([^<]*)', b)
            link = re.search(r'<a href="(https://kakaku\.com/ksearch/jump/[^"]+)"', b)
            raw, uk = _size(title)
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=htmllib.unescape(link.group(1)) if link else url,
                    variant_id="1",
                    raw_size=raw or title,
                    uk=uk,
                    color="",
                    price=float(pr.group(1).replace(",", "")),
                    currency="JPY",
                    status=IN,
                    condition=_condition(title),
                    note=f"価格.com 店铺：{shop.group(1).strip() if shop else '?'}",
                )
            )
        if total is not None and seen >= total:
            break
    if total is None or seen < total:
        # 没翻完：已抓到的照常有效，但不能判断哪些旧商品下架了
        # （不能设 res.error：主程序看到 error 会整店跳过本轮数据）
        return res
    for k in cfg.get("_known_products", []):
        if k not in res.products_checked:
            res.gone_products.add(k)
    return res
