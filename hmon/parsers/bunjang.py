"""번개장터 Bunjang（韩国二手平台）——站点自己的公开 JSON API。

搜索：https://api.bunjang.co.kr/api/search/v8/pw/product/specs/keyword?q=<q>&sort=latest
  → data.searchSpec.uiBlockList[blockType=="productList.grid.main"].searchResponse.data[]
    {pid, name, price, status("SELLING"/"RESERVED"/"SOLD_OUT"…), ad, type("PRODUCT"/广告)}；totalCount。
详情：https://api.bunjang.co.kr/api/pms/v3/products-detail/<pid>?viewerUid=-1
  → data.product {saleStatus, condition, description, qty, trade.freeShipping}
平台成色 condition：NEW → new；LIKE_NEW → like_new；LIGHTLY_USED / HEAVILY_USED / DAMAGED 等 → used（其他值按文字判断）。
每轮：搜索 1 次 + 命中件详情 ≤ max_details 次。详情失败整店作废。

cfg：
  searches: [파이브텐 하이앵글]
  max_details: 4
"""
from __future__ import annotations

import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_us_asia_common import clean, condition_from_text, finish, is_bundle, is_hiangle, merge_condition, size_from_text

API = "https://api.bunjang.co.kr/api"
PCOND = {"NEW": "new", "LIKE_NEW": "like_new"}


def _pcond(c: str | None) -> str | None:
    if not c:
        return None
    if c in PCOND:
        return PCOND[c]
    if "USED" in c or "DAMAGED" in c or "WORN" in c:
        return "used"
    return None


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    cands: dict[str, dict] = {}
    for q in cfg.get("searches", ["파이브텐 하이앵글"]):
        url = f"{API}/search/v8/pw/product/specs/keyword?q={urllib.parse.quote(q)}&sort=latest"
        try:
            d = fetch(url, expect_json=True)
            blocks = d["data"]["searchSpec"]["uiBlockList"]
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        except (KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"搜索 JSON 结构不对：{e!r}")
        main = next((b for b in blocks if b.get("blockType") == "productList.grid.main"), None)
        if main is None:
            if any(b.get("blockType", "").startswith("productList.empty") for b in blocks):
                continue  # 0 结果
            return StoreResult(store=sid, ok=False, error="找不到 productList.grid.main")
        for x in (main.get("searchResponse") or {}).get("data") or []:
            pid = str(x.get("pid") or "")
            name = clean(x.get("name", ""))
            if not pid or x.get("ad") or x.get("type", "PRODUCT") != "PRODUCT":
                continue
            if not is_hiangle(name, need_brand=False) or is_bundle(name):
                continue
            cands.setdefault(pid, x)
    for i, (pid, x) in enumerate(cands.items()):
        res.products_checked.add(pid)
        name = clean(x.get("name", ""))
        link = f"https://m.bunjang.co.kr/products/{pid}"
        if i >= int(cfg.get("max_details", 4)):
            res.obs.append(Obs(
                store=sid, product_id=pid, title=name, url=link, variant_id="1", raw_size=name[:40], uk=None,
                color="", price=float(x["price"]) if str(x.get("price", "")).isdigit() else None, currency="KRW",
                status=UNKNOWN, condition="unknown", note="本轮详情配额用完，未核实",
            ))
            continue
        try:
            p = fetch(f"{API}/pms/v3/products-detail/{pid}?viewerUid=-1", expect_json=True)["data"]["product"]
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"详情失败：{e}")
        except (KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"详情 JSON 结构不对：{e!r}")
        desc = p.get("description") or ""
        if not is_hiangle(name, desc, need_brand=True):
            continue
        sale = p.get("saleStatus") or x.get("status")
        status = IN if sale == "SELLING" and (p.get("qty") or 1) > 0 else OUT if sale in ("SOLD_OUT", "SOLD") else UNKNOWN
        pc = p.get("condition")
        cond = merge_condition(_pcond(pc), condition_from_text(name))
        if _pcond(pc) is None:
            cond = condition_from_text(name, desc)
        raw, uk = size_from_text(name, desc, korean_mm=True)
        try:
            price = float(p.get("price") or x.get("price"))
        except (TypeError, ValueError):
            price = None
        ship = "包邮" if (p.get("trade") or {}).get("freeShipping") else "运费另计"
        res.obs.append(Obs(
            store=sid, product_id=pid, title=name, url=link, variant_id="1",
            raw_size=raw or name[:40], uk=uk, color="", price=price, currency=cfg.get("currency", "KRW"),
            status=status, condition=cond,
            note=f"平台成色：{pc or '未填'}；状态：{sale}；{ship}；地区：{p.get('geoLabel', '?')}",
        ))
    return finish(res, cfg)
