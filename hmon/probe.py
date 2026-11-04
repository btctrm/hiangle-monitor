"""探测候选店铺能不能读：python -m hmon probe <域名或商品链接> ...

只打印结果，不改状态、不发通知。用来决定一家新店能不能加进 config.yaml。
- 只给域名（如 sportfits.eu）：按 Shopify 店试搜索接口，列出搜到的 Hiangle 商品和逐码库存。
- 给完整链接：抓页面，报告是否被拦截、有没有逐码的结构化数据（JSON-LD）、是不是 Shopify。
"""
from __future__ import annotations

import json
import re

from .core import FetchError, fetch
from .parsers.jsonld import _LD, _find_group


def _shopify(domain: str, query: str) -> list[str]:
    from .parsers import shopify

    out = []
    try:
        found = shopify._discover(domain, query)
    except FetchError as e:
        return [f"  Shopify 搜索：失败（{e}）"]
    hits = [(h, t) for h, t in found if "hiangle" in t.lower()]
    out.append(f"  Shopify 搜索：成功，搜到 {len(found)} 个商品，其中 Hiangle {len(hits)} 个")
    for h, t in hits:
        try:
            p = fetch(f"https://{domain}/products/{h}.js", expect_json=True)
        except FetchError as e:
            out.append(f"    - {h}：读取失败（{e}）")
            continue
        vs = p.get("variants", [])
        tracked = sum(1 for v in vs if v.get("inventory_management") == "shopify")
        avail = sum(1 for v in vs if v.get("available"))
        prices = sorted({(v.get("price") or 0) / 100 for v in vs})
        cmp_ = sorted({(v.get("compare_at_price") or 0) / 100 for v in vs} - {0})
        opts = [o.get("name") if isinstance(o, dict) else o for o in p.get("options", [])]
        sizes = [(v.get("options") or [""])[0] for v in vs][:12]
        out.append(
            f"    - {t} [{h}]：{len(vs)} 个变体，跟踪库存 {tracked}，有货 {avail}，"
            f"价格 {prices}{'，原价 ' + str(cmp_) if cmp_ else ''}，选项 {opts}，尺码样例 {sizes}"
        )
    return out


def _dump(html: str) -> list[str]:
    """导出页面样本，用来写新解析器：JSON-LD 开头、内嵌数据脚本、Hiangle 附近的原文。"""
    out = []
    for block in _LD.findall(html)[:4]:
        out.append("  [JSON-LD] " + re.sub(r"\s+", " ", block)[:1200])
    for m in re.finditer(r'<script[^>]*(?:id="(__NEXT_DATA__|__NUXT_DATA__)"|type="application/json")[^>]*>(.*?)</script>', html, re.S):
        body = m.group(2)
        i = body.lower().find("hiangle")
        if i >= 0:
            out.append(f"  [内嵌 JSON {m.group(1) or 'application/json'}，{len(body)} 字节] …" + body[max(0, i - 600):i + 900] + "…")
            break
    for m in re.finditer(r"window\.(__[A-Z_]+__|[A-Za-z_]*[Ss]tate)\s*=", html):
        out.append(f"  [内嵌变量] {m.group(0)} 位置 {m.start()}")
    body = max(html.find("<body"), 0)  # 跳过 <head>，看正文里商品卡片的写法
    for n, m in enumerate(re.finditer(r"hiangle", html[body:], re.I)):
        if n >= 3:
            break
        i = body + m.start()
        out.append("  [正文] …" + re.sub(r"\s+", " ", html[max(0, i - 400):i + 700]) + "…")
    return out


def _page(url: str, dump: bool = False) -> list[str]:
    out = []
    try:
        html = fetch(url, retries=1)
    except FetchError as e:
        return [f"  页面：失败（{e}）"]
    if dump:
        out += _dump(html)
    out.append(f"  页面：成功，{len(html)} 字节{'，是 Shopify 店' if 'cdn.shopify.com' in html else ''}")
    types, group, offers = [], None, []
    for block in _LD.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for it in data if isinstance(data, list) else [data]:
            if isinstance(it, dict):
                types.append(str(it.get("@type")))
                if it.get("@type") == "Product":
                    o = it.get("offers")
                    if isinstance(o, list):
                        offers += o
                    elif isinstance(o, dict):
                        offers += o.get("offers", [o]) if o.get("@type") == "AggregateOffer" else [o]
        group = group or _find_group(data)
    out.append(f"  JSON-LD 类型：{types or '无'}")
    if group:
        vs = group.get("hasVariant", [])
        sample = []
        for v in vs[:8]:
            o = v.get("offers") or {}
            o = o[0] if isinstance(o, list) and o else o
            sample.append(f"{v.get('size')}={str(o.get('availability', '')).rsplit('/', 1)[-1]}@{o.get('price')}{o.get('priceCurrency', '')}")
        out.append(f"  逐码数据（ProductGroup）：{len(vs)} 个尺码 → 可直接用 jsonld 解析器。样例：{sample}")
    elif offers:
        sample = [f"{o.get('name') or o.get('sku')}={str(o.get('availability', '')).rsplit('/', 1)[-1]}@{o.get('price')}" for o in offers[:8]]
        out.append(f"  Product.offers：{len(offers)} 条（需要新解析器）。样例：{sample}")
    else:
        out.append("  没有逐码的结构化数据")
    m = re.search(r"Hiangle[^<]{0,80}", html, re.I)
    out.append(f"  页面含 Hiangle：{'是' if m else '否'}")
    return out


def probe(targets: list[str], query: str = "hiangle") -> int:
    dump = "--dump" in targets  # targets 里加 --dump：额外导出页面样本
    targets = [t for t in targets if t != "--dump"]
    for t in targets:
        t = t.strip()
        if not t:
            continue
        print(f"\n### {t}")
        if "/" in t.replace("https://", "").replace("http://", ""):
            url = t if t.startswith("http") else "https://" + t
            lines = _page(url, dump)
        else:
            lines = _shopify(t.replace("https://", "").replace("http://", "").strip("/"), query)
        print("\n".join(lines), flush=True)
    return 0
