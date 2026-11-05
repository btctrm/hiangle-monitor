"""露天拍賣 Ruten（台湾）——站点自己的公开 JSON API。

搜索：https://rtapi.ruten.com.tw/api/search/v3/index.php/core/prod?q=hiangle&type=direct&sort=rnk%2Fdc&limit=80&offset=1
  → {TotalRows, Rows:[{Id}]}
详情（一次批量）：https://rapi.ruten.com.tw/api/items/v2/list?gno=<id1,id2,…>&level=detail
  → data[]：{id, name, goods_price(TWD), available, num, condition, platform("RUTEN"/"EBAY"), location,
             spec_info.specs{spec_id:{spec_name, spec_num, spec_price, spec_status}}, deliver_way}
目前命中的全是 platform=EBAY 的“海外代购”镜像（日本 eBay 卖家），价格已换成 TWD 并含露天加价；
原 eBay 美元价在 goods_ori_price/spec_ori_price，写进 note。
condition 代码：抽查露天商品——全新零售商品一律 "B"，标题写“二手”的为 H/I/J/K（成色档位含义未公开），
  所以 B → new，其他代码 → used（标题写近新时取 like_new），缺省 → 按标题关键词。
尺码：spec_name 如 "US9 (27.0cm)/UK8.5/EU42⅔"、"US8 / 26cm"、"US10(Men's)/UK9.5/EU44"、或只有 "8.5"
  （只写数字时仅在标题写 Men's 时按美码男）。spec_num=0 → 该码缺货。
available=false 的商品（露天上暂不可下单）整件记为“未知”。

cfg：
  searches: [hiangle]
"""
from __future__ import annotations

import re
import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import to_uk
from .used_us_asia_common import clean, condition_from_text, finish, gender_of, is_bundle, is_hiangle, norm, size_from_text

SEARCH = "https://rtapi.ruten.com.tw/api/search/v3/index.php/core/prod"
ITEMS = "https://rapi.ruten.com.tw/api/items/v2/list"


def _cond(code: str | None, title: str) -> str:
    t = condition_from_text(title)
    if code == "B":
        return "new" if t not in ("like_new", "used") else t
    if code:
        return "like_new" if t == "like_new" else "used"
    return t


def _size(spec: str, title: str) -> float | None:
    s = norm(spec)
    g = gender_of(title)
    if re.search(r"Men'?s", s, re.I):
        g = "M"
    s2 = re.sub(r"US\s*([\d.]+)\s*\((?:Men'?s)\)", r"US M \1", s, flags=re.I)
    uk = to_uk(s2, "AUTO", g)
    if uk is None:
        _, uk = size_from_text(s2)
    if uk is None and re.fullmatch(r"\d{1,2}(?:\.5)?", s.strip()) and g == "M":
        uk = to_uk(s.strip(), "US_M")
    return uk


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    res = StoreResult(store=sid, ok=True)
    ids: list[str] = []
    for q in cfg.get("searches", ["hiangle"]):
        url = f"{SEARCH}?q={urllib.parse.quote(q)}&type=direct&sort=rnk%2Fdc&limit=80&offset=1"
        try:
            d = fetch(url, expect_json=True)
            rows = d["Rows"]
            d["TotalRows"]
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        except (KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"搜索 JSON 结构不对：{e!r}")
        for r in rows or []:
            if r.get("Id") and r["Id"] not in ids:
                ids.append(str(r["Id"]))
    if not ids:
        return finish(res, cfg)
    items = []
    for i in range(0, len(ids), 40):  # 每批 40 个，正常 1 次请求
        try:
            d = fetch(f"{ITEMS}?gno={','.join(ids[i:i + 40])}&level=detail", expect_json=True)
            items += d["data"]
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"商品详情失败：{e}")
        except (KeyError, TypeError) as e:
            return StoreResult(store=sid, ok=False, error=f"商品详情结构不对：{e!r}")
    for x in items:
        pid = str(x.get("id") or "")
        title = clean(x.get("name", ""))
        if not pid or not is_hiangle(title) or is_bundle(title):
            continue
        res.products_checked.add(pid)
        cond = _cond(x.get("condition"), title)
        avail = bool(x.get("available"))
        src = "eBay 代购镜像" if x.get("platform") == "EBAY" else "露天卖家"
        ship = "；".join(f"{k} {v.get('cost')} TWD" for k, v in (x.get("deliver_way") or {}).items())
        link = f"https://www.ruten.com.tw/item/show?{pid}"
        specs = ((x.get("spec_info") or {}).get("specs") or {})
        base_note = f"{src}（{x.get('location', '?')}）；露天成色代码 {x.get('condition')}；运费：{ship or '?'}"
        if not specs:
            raw, uk = size_from_text(title)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=link, variant_id="1", raw_size=raw or title[:40], uk=uk,
                color="", price=float(x.get("goods_price") or 0) or None, currency="TWD",
                status=(IN if (x.get("num") or 0) > 0 else OUT) if avail else UNKNOWN, condition=cond,
                note=f"{base_note}；原价 {x.get('goods_ori_price')} {x.get('currency', '')}",
            ))
            continue
        for spec_id, s in specs.items():
            if s.get("childs"):
                continue  # 二级规格（颜色→尺码）目前没见过，遇到不猜
            name = clean(str(s.get("spec_name", "")))
            n = s.get("spec_num") or 0
            st = s.get("spec_status") == "Y"
            status = UNKNOWN if not avail else (IN if (st and n > 0) else OUT)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=link, variant_id=str(spec_id), raw_size=name,
                uk=_size(name, title), color="", price=float(s.get("spec_price") or x.get("goods_price") or 0) or None,
                currency="TWD", status=status, condition=cond,
                note=f"{base_note}；原价 {s.get('spec_ori_price')} {x.get('currency', '')}"
                     + ("" if avail else "；露天显示暂不可下单"),
            ))
    return finish(res, cfg)
