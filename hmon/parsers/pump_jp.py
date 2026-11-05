"""PUMP ONLINE STORE（日本，store.pump-climbing.com）：站内搜索 + 商品页“カラー／サイズ”弹窗 HTML。

每个尺码一个 <li>：<span>US8h 【在庫なし】</span><p>&yen;19,800</p> 后跟按钮。
双重核对：
  标签为【残りわずか】/【在庫あり】/无标签 且有 add2cart('<码>') 按钮 → 有货（【予約】等其他标签 → 未知）
  标签是【在庫なし】且只有 regrequest(<码>)（到货通知）→ 缺货
  其他组合 → 未知
尺码是美码（男/中性），"h" 表示半码：US8h = US 8.5。
"""
from __future__ import annotations

import html as htmllib
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

BASE = "https://store.pump-climbing.com"
_HI = re.compile(r"hi[\s\-]?angle|ハイアングル", re.I)
# 只有这些标签算现货；【予約】【取り寄せ】等其他标签即使能加购也记为未知
_IN_LABELS = ("", "残りわずか", "在庫あり", "在庫有り")
_LI = re.compile(r"<li>\s*<div><span>([^<]*)</span>\s*<p>([^<]*)</p>(.*?)</li>", re.S)


def _discover(cfg: dict) -> set[str]:
    page = fetch(f"{BASE}/products/search.do?k={cfg.get('search', 'hiangle')}")
    if "PUMP" not in page:
        raise FetchError("搜索页结构异常")
    return set(re.findall(r"/products/(\d+)\.html", page))


def _uk(label: str) -> float | None:
    m = re.fullmatch(r"US\s*(\d{1,2})(h)?", label.strip(), re.I)
    if not m:
        return None
    return to_uk(m.group(1) + (".5" if m.group(2) else ""), "US_M")


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    try:
        ids = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    ids |= set(cfg.get("product_ids", [])) | set(cfg.get("_known_products", []))
    if not ids:
        return StoreResult(store=sid, ok=False, error="搜索结果里没有 Hiangle（可能改版）")
    if len(ids) > 5:
        return StoreResult(store=sid, ok=False, error=f"候选商品过多（{len(ids)}）")
    for pid in sorted(ids):
        url = f"{BASE}/products/{pid}.html"
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        m = re.search(r"<title>([^<|]*)", page)
        title = htmllib.unescape(m.group(1)).strip() if m else ""
        if not _HI.search(title):
            continue
        rows = []
        for blk in page.split('<div class="popup-color-item">')[1:]:
            cm = re.search(r'popup-color-item-image">.*?<p>([^<]*)</p>', blk, re.S)
            color = htmllib.unescape(cm.group(1)).strip() if cm else ""
            rows += [(color,) + r for r in _LI.findall(blk)]
        if not rows:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到尺码列表（可能改版）")
        res.products_checked.add(pid)
        for color, span, ptxt, rest in rows:
            span = htmllib.unescape(span).strip()
            mm = re.match(r"(\S+)\s*(?:【([^】]*)】)?", span)
            raw, label = (mm.group(1), mm.group(2) or "") if mm else (span, "")
            cart = re.search(r"add2cart\('?(\d+)'?\)", rest)
            reg = re.search(r"regrequest\('?(\d+)'?\)", rest)
            code = (cart or reg).group(1) if (cart or reg) else f"{color}|{raw}"
            if label in _IN_LABELS and cart and not reg:
                status, note = IN, label
            elif label == "在庫なし" and reg and not cart:
                status, note = OUT, ""
            else:
                status, note = UNKNOWN, f"标签与按钮不一致：{label or '无'}"
            pm = re.search(r"([\d,]+)", htmllib.unescape(ptxt))
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=url,
                    variant_id=code,
                    raw_size=raw,
                    uk=_uk(raw),
                    color=color,
                    price=float(pm.group(1).replace(",", "")) if pm else None,
                    currency="JPY",
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
