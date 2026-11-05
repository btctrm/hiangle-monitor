"""billiger.de（德国比价站）。

搜索页 /search?searchstring=five+ten+hiangle&page=N 服务端渲染，每个结果卡片里有“收藏”按钮：
  data-object-id / data-object-type（product=多店比价页，offer=单店直出）/ data-name / data-price（分）
billiger 的商品按“颜色+尺码”拆开，一个卡片 = 一个尺码，所以 variant_id 固定 "1"。
价格是“ab”最低价；比价站列出即视为有货（segment aggregator，confirm_runs 1），
本轮搜索里消失的旧卡片 = 下架。
尺码只认标题末尾的 EU 码（"… 46" "… 45 1/3" "Größe 49 1⁄3"）或明确写 "EU 38"；
"Gr 5,5" "schwarz/grau 11,5" 这类不带码制的不猜。
同一款同一配色里出现 39 / 45 / 37,5 这类非 Five Ten 欧码时，同款的整数码也不换算（可能是别的欧码体系）。
没翻完全部结果时不记下架，但已抓到的数据照常返回（不设 error，否则主程序会整店跳过）。
"""
from __future__ import annotations

import html as htmllib
import re
import urllib.parse

from ..core import IN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_HI = re.compile(r"hi[\s-]?angle", re.I)
_BTN = re.compile(
    r'<button\b[^>]*?data-object-id="(\d+)"\s*data-object-type="(\w+)"\s*'
    r'data-name="([^"]*)"\s*data-price="(\d+)"'
)
_EU_TAIL = re.compile(r"(?:^|[\s,(-])((?:3[5-9]|4\d|5[0-2])(?: (?:1/3|2/3))?)\s*(?:in\b.*)?$")
_TOTAL = re.compile(r"(\d+) Ergebnisse")


def _size(name: str) -> tuple[str, float | None]:
    n = re.sub(r"\s+", " ", name.replace("⁄", "/")).strip()
    n = re.sub(r"(\d{2})\.([12]/3)", r"\1 \2", n)  # Hardloop 写法 "36.2/3"
    g = gender_from_title(n)
    if re.search(r"\bEU\s*\d", n):
        m = re.search(r"\bEU\s*(\d{2}(?: [12]/3|\.\d)?)", n)
        return (m.group(0) if m else n), to_uk(n, "AUTO", g)
    m = re.search(r"Größe (\d{2}(?:[.,]5| [12]/3)?)(?![\d/])", n) or _EU_TAIL.search(n)
    if m:
        return m.group(1), to_uk(m.group(1), "EU", g)
    return n, None


def _line(name: str) -> str:
    """同一款同一配色（去掉所有数字）。"""
    n = name.replace("⁄", "/").lower()
    return re.sub(r"\d+(?:[ .,]\d+(?:/3)?)?", "#", n).strip()


def _off_scale(raw: str) -> bool:
    """Five Ten 1/3 欧码里整数只有偶数（36…48）；出现半码或 37–51 奇数整数 = 别的欧码体系。"""
    raw = raw.strip()
    if re.fullmatch(r"(?:EU\s*)?\d{2}[.,]5", raw):
        return True
    m = re.fullmatch(r"(?:EU\s*)?(\d{2})", raw)
    return bool(m) and 37 <= int(m.group(1)) <= 51 and int(m.group(1)) % 2 == 1


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    q = urllib.parse.quote_plus(cfg.get("search", "five ten hiangle"))
    pages = int(cfg.get("max_pages", 3))
    total = None
    seen = 0
    cards: list[tuple[str, str, str, str, str]] = []  # (oid, type, name, cents, 所在页 url / 链接)
    for page in range(1, pages + 1):
        url = f"https://www.billiger.de/search?searchstring={q}" + (f"&page={page}" if page > 1 else "")
        try:
            html = fetch(url)
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        btns = _BTN.findall(html)
        if page == 1:
            m = _TOTAL.search(html)
            total = int(m.group(1)) if m else None
            if not btns and total != 0:
                return StoreResult(store=sid, ok=False, error="搜索页里找不到结果卡片（可能改版或被拦截）")
        if not btns:
            break
        seen += len(btns)
        for oid, otype, name, cents in btns:
            link = re.search(r'href="(/pricelist/' + oid + r'-[^"?]*)', html)
            cards.append((oid, otype, htmllib.unescape(name), cents, ("https://www.billiger.de" + link.group(1)) if link else url))
        if total is not None and seen >= total:
            break

    res = StoreResult(store=sid, ok=True)
    parsed = [(c, _size(c[2])) for c in cards if _HI.search(c[2])]
    # 某款某配色里出现过 39 / 45 / 37,5 这类非 Five Ten 欧码：同款的整数码（40、42…）可能也是别的体系，不换算
    odd = {_line(c[2]) for c, (raw, _) in parsed if _off_scale(raw)}
    for (oid, otype, name, cents, purl), (raw, uk) in parsed:
        pid = f"{otype}:{oid}"
        if pid in res.products_checked:
            continue
        res.products_checked.add(pid)
        if _line(name) in odd and re.fullmatch(r"(?:EU\s*)?\d{2}(?:[.,]5)?", raw.strip()):
            uk = None
        res.obs.append(
            Obs(
                store=sid,
                product_id=pid,
                title=name,
                url=purl,
                variant_id="1",
                raw_size=raw,
                uk=uk,
                color="",
                price=int(cents) / 100,
                currency="EUR",
                status=IN,
                condition="new",
                note="billiger.de " + ("多店比价，最低价" if otype == "product" else "单店报价"),
            )
        )
    # 只有确认翻完全部结果，才能把没出现的旧卡片记为下架；没翻完时已抓到的数据照常有效
    # （不能设 res.error：主程序看到 error 会整店跳过本轮数据）
    if total is not None and seen >= total:
        for k in cfg.get("_known_products", []):
            if k not in res.products_checked:
                res.gone_products.add(k)
    return res
