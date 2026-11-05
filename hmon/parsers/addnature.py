"""Addnature（addnature.com，瑞典站 SEK，奥特莱斯清仓为主）。

页面只列出有货尺码（清仓款只剩零星 2 个码，如 46 2/3、49 1/3），不给逐码库存数字；
逐码库存要选尺码后 ASP.NET 回发（表单提交，禁止），所以采用“列出的码 = 有货”的口径，并做两路核对：
  1) 分类页（Five Ten 攀岩鞋）每个商品卡片的 <ul class="matrixvalues"> 尺码列表 + 价格
  2) 商品页 schema.org 微数据 price / availability + 尺码下拉框 ddlMatrixType 的 <option>
两边尺码一致且 availability=InStock 才记有货；不一致记未知。没再列出的尺码由主程序记为缺货。
"""
from __future__ import annotations

import html as _html
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import eu_to_uk

BASE = "https://www.addnature.com"
_HIANGLE = re.compile(r"hi[\s-]?angle", re.I)
_SIZE = re.compile(r"^\d{2}(?: [12]/3)?$")


def _listing(html: str) -> dict[str, dict]:
    out = {}
    for chunk in html.split('<div class="grid-unit">')[1:]:
        a = re.search(r'href="/sv/articles/(2\.\d+\.\d+)/([^"]+)" title="([^"]+)"', chunk)
        if not a or not _HIANGLE.search(a.group(3) + a.group(2)):
            continue
        mv = re.search(r'<ul class="matrixvalues">(.*?)</ul>', chunk, re.S)
        sizes = [_html.unescape(s) for s in re.findall(r'<li title="([^"]+)"', mv.group(1))] if mv else []
        out[a.group(1)] = {"slug": a.group(2), "title": _html.unescape(a.group(3)),
                           "sizes": [s for s in sizes if _SIZE.match(s)]}
    return out


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    try:
        cat = fetch(BASE + cfg.get("category", "/sv/articles/8643/five-ten-klatterskor"))
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"分类页失败：{e}")
    if '<div class="grid-unit">' not in cat:
        return StoreResult(store=sid, ok=False, error="分类页结构不对（可能改版）")
    listed = _listing(cat)
    pids = set(listed) | set(cfg.get("_known_products", [])) | set(cfg.get("product_ids", []))

    for pid in sorted(pids)[: int(cfg.get("max_products", 5))]:
        info = listed.get(pid)
        url = f"{BASE}/sv/articles/{pid}/{info['slug'] if info else 'x'}"
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        price = re.search(r'itemprop="price" content="([\d.]+)"', page)
        avail = re.search(r'itemprop="availability" content="(\w+)"', page)
        cur = re.search(r'itemprop="priceCurrency" content="([A-Z]{3})"', page)
        title_m = re.search(r'<title>\s*(?:Shoppa\s+)?([^<]*?)\s*-\s*Addnature', page)
        sel = re.search(r'<select[^>]*ddlMatrixType[^>]*>(.*?)</select>', page, re.S)
        if not title_m:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到商品标题（可能改版）")
        title = _html.unescape(title_m.group(1))
        if not _HIANGLE.search(title):
            # Addnature 只按 ID 末段路由：商品删除后同一 ID 会跳到别的商品（实测 2.4646.69999 → Hydro Flask）。
            # 这个 ID 来自配置/已知/分类页里的 Hiangle，现在指向非 Hiangle = 原商品已下架。
            res.gone_products.add(pid)
            continue
        if not price or not avail:
            if re.search(r'property="product:availability" content="(?:out of stock|oos)"', page) and not sel:
                res.products_checked.add(pid)  # 明确标注缺货、无尺码下拉：整款无货
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到价格/库存字段（可能改版）")
        opts = []
        if sel:
            opts = [(v, _html.unescape(t).strip()) for v, t in
                    re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]+)</option>', sel.group(1)) if v != "0"]
        opts = [(v, t) for v, t in opts if _SIZE.match(t)]
        res.products_checked.add(pid)
        if avail.group(1) != "InStock":
            continue  # 整款无货：不产出尺码，之前的尺码由主程序记为缺货
        if not opts:
            # 标着 InStock 却解析不到任何尺码：结构变了，不能把旧尺码当缺货
            return StoreResult(store=sid, ok=False, error=f"{pid}: InStock 但找不到尺码下拉（可能改版）")
        page_sizes = sorted(t for _, t in opts)
        list_sizes = sorted((info or {}).get("sizes", []))
        agree = info is not None and page_sizes == list_sizes
        for v, t in opts:
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=url, variant_id=v,
                raw_size=f"EU {t}", uk=eu_to_uk(t), color="",
                price=float(price.group(1)), currency=cur.group(1) if cur else cfg.get("currency", "SEK"),
                status=IN if agree else UNKNOWN, condition="new",
                note="" if agree else f"分类页尺码 {list_sizes} 与商品页 {page_sizes} 不一致",
            ))
    if not res.products_checked and not res.gone_products:
        return StoreResult(store=sid, ok=False, error="没有解析到任何 Hiangle 商品")
    return res
