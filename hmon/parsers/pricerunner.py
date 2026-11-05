"""PriceRunner（Klarna 比价站，UK=pricerunner.com / SE / DK）。

页面里有 <script id="initial_payload" type="application/json">，其中
__DEHYDRATED_QUERY_STATE__.queries 是 React-Query 的缓存：
  - 搜索页 /results?q=hiangle：queryKey[0]=="serp-search"，pages[].products[]（id/name/url/lowestPrice）
  - 商品页 /pl/<cat>-<id>/...：queryKey[0]=="product-detail-offers"，offers[]（每个商户每个尺码一条，
    带 stockStatus / price / merchantId），merchants{id: {name}}
PriceRunner 默认只列出非缺货 offer；本轮商品页里消失的 offer 由主程序记为缺货。
尺码只从 offer 名称末尾的 EU 码取（"…, 40" "… - 46 2/3" "… 46.2/3" "…(49 1/3)"），
没有 EU 码时交给 to_uk(AUTO)（如 "(WMNS) … US 7"）；"Storlek 11,5" 这类不带码制的不猜，标码制不明。
同一商户同一款里只要出现半码（39.5）或奇数整数欧码（45），说明它用的不是 Five Ten 1/3 欧码表，
这一款的整数码（40、46）也不换算（Outnorth 的 White/Coreblack 就是这样）。

cfg：
  domain: www.pricerunner.com      # UK 站（.co.uk 会 301 到 .com）
  search: hiangle
  max_products: 5                  # 每轮最多抓几个商品页（超出时按小时轮换）
  product_ids: [3926466, ...]      # 可选：搜索里没出现也要查的商品
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_PAYLOAD = re.compile(r'<script id="initial_payload"[^>]*>(.*?)</script>', re.S)
_HI = re.compile(r"hi[\s-]?angle|ハイアングル|하이앵글", re.I)
_NOT_SHOE = re.compile(r"\b(sock|bag|brush|chalk|insole)s?\b", re.I)
# offer 名称末尾的 EU 码
_EU_TAIL = re.compile(
    r"(?:^|[\s,(-])((?:3[5-9]|4\d|5[0-2])(?:[ .](?:1/3|2/3)|\.5)?)\s*(?:\((?:[^)]*)\))?\s*$"
)


def _queries(html: str) -> list:
    m = _PAYLOAD.search(html)
    if not m:
        raise ValueError("找不到 initial_payload（可能改版或被拦截）")
    d = json.loads(m.group(1))
    return d["__DEHYDRATED_QUERY_STATE__"]["queries"]


def _query_data(queries: list, key: str):
    for q in queries:
        qk = q.get("queryKey") or []
        if qk and qk[0] == key:
            return (q.get("state") or {}).get("data")
    return None


_EU_PAREN = re.compile(r"\(((?:3[5-9]|4\d|5[0-2])(?: (?:1/3|2/3))?)\)\s*$")


def _size_of(name: str) -> str:
    m = _EU_PAREN.search(name.strip()) or _EU_TAIL.search(name.strip())
    if not m:
        return ""
    return m.group(1).replace(".1/3", " 1/3").replace(".2/3", " 2/3")


_UK_SUFFIX = re.compile(r"(?:^|[\s,(-])(\d{1,2}(?:[.,]5)?)\s?UK\s*\)?\s*$", re.I)  # "Core Black - 6.5UK"


def _line(name: str) -> str:
    """同一商户同一款（去掉所有数字）——用来判断这一条线用的是不是 Five Ten 的 1/3 欧码。"""
    return re.sub(r"\d+(?:[ .,]\d+(?:/3)?)?", "#", name.lower()).strip()


def _off_scale(raw: str) -> bool:
    """39.5 / 41.5 / 45 这类写法：Five Ten 1/3 欧码里整数只有偶数（36、38…48），
    出现半码或 37–51 的奇数整数，说明这家用的是别的欧码体系（35 不算：Hardloop 等 1/3 体系也会列 35）。"""
    if re.fullmatch(r"\d{2}[.,]5", raw):
        return True
    return bool(re.fullmatch(r"\d{2}", raw)) and 37 <= int(raw) <= 51 and int(raw) % 2 == 1


def _status(o: dict) -> str:
    st = o.get("stockStatus")
    if st == "OUT_OF_STOCK":
        return OUT
    if st == "IN_STOCK" and o.get("availability") == "AVAILABLE":
        return IN
    return UNKNOWN


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    base = "https://" + cfg.get("domain", "www.pricerunner.com")
    q = cfg.get("search", "hiangle")
    try:
        html = fetch(f"{base}/results?q={urllib.parse.quote(q)}")
        data = _query_data(_queries(html), "serp-search")
    except (FetchError, ValueError, KeyError) as e:
        return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
    if not data or "pages" not in data:
        return StoreResult(store=sid, ok=False, error="搜索结果结构不对（serp-search 缺失）")

    found: dict[str, dict] = {}
    for page in data["pages"]:
        for p in page.get("products") or []:
            name = p.get("name", "")
            if _HI.search(name) and not _NOT_SHOE.search(name) and p.get("url"):
                found[str(p["id"])] = p
    want = list(found)
    for pid in cfg.get("product_ids", []) or []:
        if str(pid) not in want:
            want.append(str(pid))
    want.sort()
    n = int(cfg.get("max_products", 5))
    if len(want) > n:  # 超出请求预算：按小时轮换
        off = int(time.time() // 3600) % len(want)
        want = (want + want)[off:off + n]

    res = StoreResult(store=sid, ok=True)
    for pid in want:
        path = (found.get(pid) or {}).get("url") or f"/pl/337-{pid}/x"
        url = base + path
        try:
            phtml = fetch(url)
            qs = _queries(phtml)
        except FetchError as e:
            if "404" in str(e):
                res.gone_products.add(pid)
                continue
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        except (ValueError, KeyError) as e:
            return StoreResult(store=sid, ok=False, error=f"{url}: {e}")
        od = _query_data(qs, "product-detail-offers")
        info = (_query_data(qs, "product-detail-initial") or {}).get("product") or {}
        if not od or not isinstance(od.get("offers"), list):
            return StoreResult(store=sid, ok=False, error=f"{url}: 找不到 offers 数据")
        title = info.get("name") or (found.get(pid) or {}).get("name", "")
        if not _HI.search(title):
            continue
        res.products_checked.add(pid)
        merchants = od.get("merchants") or {}
        # 某商户某款里只要出现 39.5 / 45 这类非 Five Ten 欧码，同一款的整数码（40、46…）也可能是别的体系：不换算
        odd_lines = {
            (str(o.get("merchantId", "")), _line(str(o.get("name", ""))))
            for o in od["offers"]
            if _off_scale(_size_of(str(o.get("name", ""))))
        }
        seen = set()
        for o in od["offers"]:
            oname = str(o.get("name", ""))
            if not _HI.search(oname):
                continue
            mid = str(o.get("merchantId", ""))
            norm = re.sub(r"\s+", " ", oname.strip().lower())
            vid = f"{mid}|{norm}"
            if vid in seen:
                continue
            seen.add(vid)
            mname = (merchants.get(mid) or {}).get("name", mid)
            raw = _size_of(oname)
            gender = gender_from_title(oname) or gender_from_title(title)
            if raw:
                if (mid, _line(oname)) in odd_lines and re.fullmatch(r"\d{2}(?:[.,]5)?", raw):
                    uk = None  # 同款出现过非 1/3 欧码：整数码不猜
                else:
                    uk = to_uk(raw, "EU", gender)
            else:
                mu = _UK_SUFFIX.search(oname)
                uk = to_uk(mu.group(1), "UK") if mu else to_uk(oname, "AUTO", gender)
            price = (o.get("price") or {})
            res.obs.append(
                Obs(
                    store=sid,
                    product_id=pid,
                    title=f"{oname} @ {mname}",
                    url=url,
                    variant_id=vid,
                    raw_size=raw or oname,
                    uk=uk,
                    color="",
                    price=float(price["amount"]) if price.get("amount") else None,
                    currency=price.get("currency") or cfg.get("currency", ""),
                    status=_status(o),
                    condition="new",
                    note=f"商户 {mname}；{o.get('stockStatus')}/{o.get('availability')}；offer：{oname}",
                )
            )
    # 搜索成功：搜索里不再出现、且不在固定清单里的旧商品 = 下架
    fixed = {str(x) for x in cfg.get("product_ids", []) or []}
    for k in cfg.get("_known_products", []):
        if k not in found and k not in fixed:
            res.gone_products.add(k)
    return res
