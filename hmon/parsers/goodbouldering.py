"""グッぼる goodbouldering.com（日本，ColorMe Shop）：站内搜索 + 商品页内嵌 "product":{…,"variants":[…]}。

每个变体：option1_value = 尺码（美码，Pro 写成 "7.0(25.0cm)"），option2_value = 颜色，stock_num = 库存数。
stock_num > 0 → 有货；== 0 → 缺货；缺字段 → 未知。
女款（名称含 WMS / ウーマン / レディース）只写裸数字，美码男女不明 → 码制不明（不猜）。
页面是 EUC-JP，但内嵌 JSON 用 \\u 转义，不受编码影响。
"""
from __future__ import annotations

import json
import re

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk

BASE = "https://goodbouldering.com"
_HI = re.compile(r"hi[\s\-]?angle|ハイアングル", re.I)
_WMS = re.compile(r"\bWMS\b|ウーマン|レディース|women", re.I)


def _discover(cfg: dict) -> set[str]:
    page = fetch(f"{BASE}/?mode=srh&keyword={cfg.get('search', 'hiangle')}")
    if "Colorme" not in page and "colorme" not in page:
        raise FetchError("搜索页结构异常")
    return set(re.findall(r"\?pid=(\d+)", page))


def _product(page: str):
    i = page.find('"product":{')
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(page, i + len('"product":'))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and isinstance(obj.get("variants"), list) else None


def _uk(raw: str, womens: bool) -> float | None:
    s = raw.strip()
    m = re.search(r"(\d{2}(?:\.5)?)(?:\.0)?\s*cm", s)
    if m:  # 有 cm 就以 cm 为准
        return to_uk(m.group(1) + "cm", "AUTO")
    if womens:
        return None
    m = re.fullmatch(r"(\d{1,2}(?:\.5)?)(?:\.0)?", s)
    return to_uk(m.group(1), "US_M") if m else None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    try:
        pids = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    pids |= set(cfg.get("product_ids", [])) | set(cfg.get("_known_products", []))
    if not pids:
        return StoreResult(store=sid, ok=False, error="搜索结果为空（可能改版）")
    if len(pids) > 5:
        return StoreResult(store=sid, ok=False, error=f"候选商品过多（{len(pids)}）")
    for pid in sorted(pids):
        url = f"{BASE}/?pid={pid}"
        try:
            page = fetch(url)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{pid}: {e}")
        p = _product(page)
        if p is None:
            return StoreResult(store=sid, ok=False, error=f"{pid}: 找不到内嵌商品数据（可能改版）")
        title = str(p.get("name", ""))
        if str(p.get("id")) != pid:
            # ColorMe 删除商品后 ?pid= 会落到首页/别的商品
            res.gone_products.add(pid)
            continue
        if not _HI.search(title):
            continue
        res.products_checked.add(pid)
        womens = bool(_WMS.search(title))
        for v in p["variants"]:
            raw = str(v.get("option1_value", ""))
            sn = v.get("stock_num")
            status = IN if isinstance(sn, int) and sn > 0 else OUT if sn == 0 else UNKNOWN
            price = v.get("option_price_including_tax") or p.get("sales_price_including_tax")
            note = f"库存 {sn}" if status == IN else ""
            if "廃番" in title:
                note = (note + "；" if note else "") + "店铺标注廃番（停产）"
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=title,
                    url=url,
                    variant_id=str(v.get("model_number") or v.get("id")),
                    raw_size=raw,
                    uk=_uk(raw, womens),
                    color=str(v.get("option2_value", "")),
                    price=float(price) if price is not None else None,
                    currency="JPY",
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    return res
