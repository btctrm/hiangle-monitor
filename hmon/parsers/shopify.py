"""Shopify 店铺：站内搜索发现商品 + 读 /products/<handle>.js 的逐码库存。

防误报：
- 只认 inventory_management == "shopify"（库存被跟踪）的变体；不跟踪库存的变体 available 永远为真，记为未知。
- 注意：实测（2026-09-30）SpokeX、Délire 的缺货尺码也能加进购物车（到结账才拦），
  所以“能加购物车”不能当有货证据，本程序不用它。
"""
from __future__ import annotations

import re
from urllib.parse import quote

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

SIZE_OPTION_NAMES = ("size", "taille", "pointure", "shoe size", "größe", "grösse", "サイズ")


def _discover(domain: str, query: str) -> list[str]:
    url = (
        f"https://{domain}/search/suggest.json?q={quote(query)}"
        "&resources[type]=product&resources[limit]=10"
        "&resources[options][unavailable_products]=last"
    )
    data = fetch(url, expect_json=True)
    try:
        prods = data["resources"]["results"]["products"]
    except (KeyError, TypeError):
        raise FetchError("搜索接口结构异常")
    handles = []
    for p in prods:
        m = re.search(r"/products/([^/?#]+)", p.get("url", ""))
        if m:
            handles.append((m.group(1), p.get("title", "")))
    return handles


_GRADE = {"new": "全新", "like new": "几乎全新", "excellent": "极好", "good": "良好", "fair": "一般", "poor": "较差"}


def _condition_detail(cfg: dict, product: dict) -> tuple[str, str]:
    """返回 (成色, 说明)。寄卖/二手店（如 Geartrade）把成色写在标签或描述里：
    标签 mm-google-shopping-condition-good；描述 “Product Condition: ... is in Good condition. ...”。"""
    cond = _condition(cfg, product)
    tags = [str(t).lower() for t in product.get("tags", [])]
    desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", product.get("description") or "")).strip()
    grade = next((t.rsplit("-", 1)[-1] for t in tags if t.startswith("mm-google-shopping-condition-")), "")
    m = re.search(r"Product Condition:\s*(.{0,200}?)(?:Size:|Color:|Retail Cost:|$)", desc, re.I)
    m2 = re.search(r"\bin (like new|excellent|good|fair|poor|new) condition", desc, re.I)
    if m2:
        grade = m2.group(1).lower()
    if grade and cfg.get("condition") == "tags":
        cond = "new" if grade == "new" else "used"
    parts = []
    if grade:
        parts.append(f"店铺标的成色：{_GRADE.get(grade, grade)}（{grade}）")
    if m:
        parts.append("店铺描述：" + m.group(1).strip()[:160])
    if not grade and cfg.get("condition") == "tags":
        hints = [t for t in product.get("tags", []) if re.search(r"off$|vendor|promo|consign", str(t), re.I)]
        parts.append("店铺没写成色" + (f"（标签：{'、'.join(map(str, hints[:4]))}）" if hints else "") + "，请看商品图")
    return cond, "；".join(parts)


def _condition(cfg: dict, product: dict) -> str:
    mode = cfg.get("condition", "new")
    if mode in ("new", "used"):
        return mode
    tags = [t.lower() for t in product.get("tags", [])]
    title = product.get("title", "").lower()
    for t in cfg.get("used_tags", []):
        if t.lower() in tags:
            return "used"
    if re.search(r"\bused\b|pre-owned|second hand|occasion", title):
        return "used"
    return "unknown"


def scan(cfg: dict) -> StoreResult:
    sid, domain = cfg["id"], cfg["domain"]
    res = StoreResult(store=sid, ok=True)
    must = [w.lower() for w in cfg.get("title_must", ["hiangle"])]
    try:
        # discover: false = 店铺站内搜索接口用不了，只读 handles 里写死的商品页
        found = _discover(domain, cfg.get("search", "hiangle")) if cfg.get("discover", True) else []
    except FetchError as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    handles = {h for h, t in found if all(w in t.lower() for w in must)}
    handles |= set(cfg.get("handles", [])) | set(cfg.get("_known_products", []))

    for h in sorted(handles):
        try:
            p = fetch(f"https://{domain}/products/{h}.js", expect_json=True)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(h)  # 商品已下架：它的所有尺码按缺货处理
                continue
            return StoreResult(store=sid, ok=False, error=f"{h}: {e}")
        title = p.get("title", "")
        if not all(w in title.lower() for w in must):
            continue
        res.products_checked.add(h)
        opts = [o.get("name", "").lower() if isinstance(o, dict) else str(o).lower() for o in p.get("options", [])]
        size_idx = next((i for i, n in enumerate(opts) if n in SIZE_OPTION_NAMES), None)
        if size_idx is None:  # 如 GearX 的 “Footwear Size (Men's)”
            size_idx = next((i for i, n in enumerate(opts) if any(k in n for k in SIZE_OPTION_NAMES)), None)
        if size_idx is None and len(opts) == 1:
            size_idx = 0
        # 尺码选项名里写了男女（如 “(Men's)”）就以它为准
        gender = cfg.get("gender") or (gender_from_title(opts[size_idx]) if size_idx is not None else None) or gender_from_title(title)
        cond, cond_note = _condition_detail(cfg, p)
        for v in p.get("variants", []):
            raw = (v.get("options") or [None] * 3)[size_idx] if size_idx is not None else v.get("title", "")
            raw = raw or ""
            tracked = v.get("inventory_management") == "shopify"
            if not tracked:
                status, note = UNKNOWN, "店铺未跟踪库存"
            else:
                status, note = (IN if v.get("available") else OUT), ""
            if cond_note:
                note = "；".join(x for x in (note, cond_note) if x)
            cmp_at, price = v.get("compare_at_price") or 0, v.get("price") or 0
            if cmp_at > price > 0:
                note = "；".join(x for x in (note, f"原价 {cmp_at / 100:g}（现价约 {price / cmp_at * 10:.1f} 折）") if x)
            color = " / ".join(
                o for i, o in enumerate(v.get("options") or []) if i != size_idx and o
            )
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=h,
                    title=title,
                    url=f"https://{domain}/products/{h}?variant={v['id']}",
                    variant_id=str(v["id"]),
                    raw_size=str(raw),
                    uk=to_uk(raw, cfg.get("size_system", "AUTO"), gender),
                    color=color,
                    price=(v.get("price") or 0) / 100,
                    currency=cfg["currency"],
                    status=status,
                    condition=cond,
                    note=note,
                )
            )
    if not res.products_checked and not cfg.get("allow_empty", True):
        return StoreResult(store=sid, ok=False, error="一个商品都没找到")
    return res
