"""Shopify 店铺（扩展版）：适用于通用 shopify 解析器不够用的店。

和 shopify.py 的区别：
- 发现商品的方式可选：discover: suggest（/search/suggest.json）/ search_html（站内搜索页里的 /products/ 链接）/ none。
  有些店的 suggest.json 返回 417（如 goofee.shop、chamonix.com.hk），只能用搜索页。
- 尺码选项按名称“包含” size / サイズ 等识别（GearX 的选项名是 "Footwear Size (Men's)"）；
  size_from_option_name: true 时，选项名里写了 Men's / Women's 就按美码男/女换算。
- 单变体商品（Default Title）照常输出，尺码记为码制不明。
防误报：只认 inventory_management == "shopify" 的变体，其他记为未知。
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

HIANGLE = re.compile(r"hi[\s\-_]?angle|ハイアングル|하이앵글", re.I)
_SIZE_WORDS = ("size", "サイズ", "taille", "pointure", "größe", "grösse")


def _discover(cfg: dict) -> set[str]:
    domain, mode = cfg["domain"], cfg.get("discover", "suggest")
    q = quote(cfg.get("search", "hiangle"))
    if mode == "none":
        return set()
    if mode == "suggest":
        data = fetch(
            f"https://{domain}/search/suggest.json?q={q}&resources[type]=product"
            "&resources[limit]=10&resources[options][unavailable_products]=last",
            expect_json=True,
        )
        try:
            prods = data["resources"]["results"]["products"]
        except (KeyError, TypeError):
            raise FetchError("搜索接口结构异常")
        return {p["handle"] for p in prods if p.get("handle") and HIANGLE.search(p.get("title", ""))}
    if mode == "search_html":
        html = fetch(f"https://{domain}/search?q={q}&type=product")
        if "/products/" not in html and "shopify" not in html.lower():
            raise FetchError("搜索页结构异常")
        out = set()
        for h in re.findall(r'/products/([^"\'?#/\s<>]+)', html):
            h = unquote(h)
            if re.search(r"\.(jpe?g|png|gif|webp|avif|js|json)$", h, re.I):
                continue
            if HIANGLE.search(h):
                out.add(h)
        return out
    raise FetchError(f"未知 discover 方式：{mode}")


def _norm_size(raw: str) -> str:
    # "US6.0(24cm)" / "10.0" -> 去掉 .0，sizes.to_uk 只认整数或 .5
    return re.sub(r"(\d)\.0(?!\d)", r"\1", raw)


def _uk(raw: str, system: str, gender: str | None) -> float | None:
    # "US6.0(24cm)" 这类同时写美码和 cm 的，以 cm 为准（不受标题男女判断影响）
    m = re.search(r"(\d{2}(?:\.5)?)(?:\.0)?\s*cm", raw, re.I)
    if m and system.upper() == "AUTO":
        return to_uk(m.group(1) + "cm", "AUTO")
    return to_uk(_norm_size(raw), system, gender)


def scan(cfg: dict) -> StoreResult:
    sid, domain = cfg["id"], cfg["domain"]
    res = StoreResult(store=sid, ok=True)
    try:
        handles = _discover(cfg)
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    handles |= set(cfg.get("handles", [])) | set(cfg.get("_known_products", []))
    if not handles:
        return StoreResult(store=sid, ok=False, error="一个 Hiangle 商品都没找到（搜索可能改版）")
    if len(handles) > cfg.get("max_products", 5):
        return StoreResult(store=sid, ok=False, error=f"候选商品过多（{len(handles)}），请检查过滤条件")

    for h in sorted(handles):
        try:
            p = fetch(f"https://{domain}/products/{quote(h)}.js", expect_json=True)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(h)
                continue
            return StoreResult(store=sid, ok=False, error=f"{h}: {e}")
        title = p.get("title", "")
        if not HIANGLE.search(title) or not isinstance(p.get("variants"), list):
            continue
        res.products_checked.add(h)
        opts = [o.get("name", "") if isinstance(o, dict) else str(o) for o in p.get("options", [])]
        size_idx = next((i for i, n in enumerate(opts) if any(w in n.lower() for w in _SIZE_WORDS)), None)
        if size_idx is None and len(opts) == 1 and opts[0].lower() != "title":
            size_idx = 0
        system = cfg.get("size_system", "AUTO")
        if size_idx is not None and cfg.get("size_from_option_name"):
            n = opts[size_idx].lower()
            if "women" in n:
                system = "US_W"
            elif "men" in n:
                system = "US_M"
            elif system == "US_M" and gender_from_title(title) == "W":
                system = "US_W"  # 选项名没写男女、标题是女款：不能按美码男换算
        gender = cfg.get("gender") or gender_from_title(title)
        for v in p["variants"]:
            vopts = v.get("options") or []
            raw = str(vopts[size_idx]) if size_idx is not None and size_idx < len(vopts) else ""
            if v.get("inventory_management") == "shopify":
                status, note = (IN if v.get("available") else OUT), ""
            else:
                status, note = UNKNOWN, "店铺未跟踪库存"
            if size_idx is None:
                note = (note + "；" if note else "") + "单一款式，页面未标尺码"
            color = " / ".join(o for i, o in enumerate(vopts) if i != size_idx and o and o != "Default Title")
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=h,
                    title=title,
                    url=f"https://{domain}/products/{quote(h)}?variant={v['id']}",
                    variant_id=str(v["id"]),
                    raw_size=raw,
                    uk=_uk(raw, system, gender) if raw else None,
                    color=color,
                    price=(v.get("price") or 0) / 100,
                    currency=cfg["currency"],
                    status=status,
                    condition="new",
                    note=note,
                )
            )
    if not res.products_checked and not res.gone_products:
        return StoreResult(store=sid, ok=False, error="找到的商品里没有 Hiangle（可能改版）")
    return res
