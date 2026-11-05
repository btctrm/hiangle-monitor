"""Yahoo!ショッピング 店铺（如 Goofee）：店内搜索页发现商品 + 商品页 __NEXT_DATA__ 的逐码库存。

商品页 props.pageProps.item：
  name / applicablePrice（含税实价）/ stockTableOneAxis.firstOption.choiceList[]
  每个 choice：choiceName（"US8.0(26cm)"）、skuId、price（为 null 时用 applicablePrice）、
               stock.isAvailable / quantity / stockText
判定：isAvailable 且 quantity>0（或 stockText 不是“在庫なし”）→ 有货；
      not isAvailable 且 quantity==0 → 缺货；预约/超卖（isReserveOverdraft）或其他组合 → 未知。
二轴表（颜色×尺码）的商品暂不支持，遇到就整店报错，不输出半截数据。
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

_HI = re.compile(r"hi[\s\-]?angle|ハイアングル", re.I)
_ND = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _discover(cfg: dict) -> set[str]:
    shop = cfg["shop"]
    page = fetch(f"https://store.shopping.yahoo.co.jp/{shop}/search.html?p={quote(cfg.get('search', 'hiangle'))}")
    if "__NEXT_DATA__" not in page:
        raise FetchError("搜索页结构异常")
    srids = set(re.findall(rf"store\.shopping\.yahoo\.co\.jp/{re.escape(shop)}/([a-z0-9_-]+)\.html", page))
    return srids - {"search", "guide", "info", "index", "privacy"}


def _uk(raw: str) -> float | None:
    m = re.search(r"(\d{2}(?:\.5)?)(?:\.0)?\s*cm", raw)
    return to_uk(m.group(1) + "cm", "AUTO") if m else None


def scan(cfg: dict) -> StoreResult:
    sid, shop = cfg["id"], cfg["shop"]
    res = StoreResult(store=sid, ok=True)
    try:
        srids = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    srids |= set(cfg.get("srids", [])) | set(cfg.get("_known_products", []))
    if not srids:
        return StoreResult(store=sid, ok=False, error="搜索结果为空（可能改版）")
    if len(srids) > 5:
        return StoreResult(store=sid, ok=False, error=f"候选商品过多（{len(srids)}）：{sorted(srids)[:8]}")
    for srid in sorted(srids):
        url = f"https://store.shopping.yahoo.co.jp/{shop}/{srid}.html"
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(srid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{srid}: {e}")
        m = _ND.search(page)
        try:
            item = json.loads(m.group(1))["props"]["pageProps"]["item"] if m else None
        except (ValueError, KeyError, TypeError):
            item = None
        if not isinstance(item, dict):
            return StoreResult(store=sid, ok=False, error=f"{srid}: 找不到商品数据（可能改版）")
        title = str(item.get("name", ""))
        if not _HI.search(title):
            continue
        if item.get("stockTableTwoAxis"):
            return StoreResult(store=sid, ok=False, error=f"{srid}: 二轴库存表暂不支持")
        try:
            choices = item["stockTableOneAxis"]["firstOption"]["choiceList"]
        except (KeyError, TypeError):
            return StoreResult(store=sid, ok=False, error=f"{srid}: 找不到逐码库存表（可能改版）")
        res.products_checked.add(srid)
        base_price = item.get("applicablePrice")
        cond = "used" if item.get("isUsed") else "new"
        for c in choices:
            st = c.get("stock") or {}
            avail, qty, text = st.get("isAvailable"), st.get("quantity"), str(st.get("stockText", ""))
            if st.get("isReserveOverdraft"):
                status, note = UNKNOWN, "可预约/超卖"
            elif item.get("isNormalPurchaseDisable") and avail is not False:
                status, note = UNKNOWN, "商品页不可普通购买（isNormalPurchaseDisable）"
            elif avail is True and (
                (isinstance(qty, int) and not isinstance(qty, bool) and qty > 0)
                # 店铺隐藏数量时（quantity=null）只认明确的“有货”文字；quantity=0 却可买（取り寄せ等）记为未知
                or (qty is None and re.search(r"在庫あり|残り|在庫有", text))
            ):
                status, note = IN, text
            elif avail is False and (qty in (0, None)):
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"isAvailable={avail} quantity={qty} {text}"
            raw = str(c.get("choiceName", ""))
            price = c.get("price") if c.get("price") is not None else base_price
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=srid,
                    title=title,
                    url=url,
                    variant_id=str(c.get("skuId") or raw),
                    raw_size=raw,
                    uk=_uk(raw),
                    color="",
                    price=float(price) if price is not None else None,
                    currency="JPY",
                    status=status,
                    condition=cond,
                    note=note,
                )
            )
    return res
