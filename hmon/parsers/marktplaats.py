"""Marktplaats.nl / 2dehands.be（Adevinta Benelux，同一套接口）。

站点自己的公开 JSON：https://<domain>/lrp/api/search?query=hiangle&limit=100&offset=0
→ listings[]：itemId / title / description / priceInfo{priceCents, priceType} / vipUrl /
attributes[] 里 key=="condition" 的 value（Nieuw / Zo goed als nieuw / Gebruikt …）。
搜索是模糊匹配（"hiangle" 会返回各种 klimschoenen），必须按标题+描述过滤 hi[ -]?angle。
priceType：FIXED=一口价、MIN_BID=起拍价（仍记价格并注明）、FAST_BID/BID/SEE_DESCRIPTION 等 → 无价格。

cfg：
  domain: www.marktplaats.nl
  searches: [hiangle, hi angle, five ten klimschoenen]   # 每个 1 次请求
"""
from __future__ import annotations

import urllib.parse

from ..core import IN, UNKNOWN, FetchError, Obs, StoreResult, fetch
from .used_eu_common import (clean, condition_from_text, finish, hiangle_match, is_reserved, merge_condition,
                             size_from_text)

_COND = {
    "nieuw": "new", "zo goed als nieuw": "like_new", "gebruikt": "used",
    "neuf": "new", "comme neuf": "like_new", "utilisé": "used", "usagé": "used",
}


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    base = "https://" + cfg.get("domain", "www.marktplaats.nl")
    res = StoreResult(store=sid, ok=True)
    for q in cfg.get("searches", ["hiangle"]):
        url = f"{base}/lrp/api/search?query={urllib.parse.quote(q)}&limit=100&offset=0"
        try:
            d = fetch(url, expect_json=True)
            if not isinstance(d, dict) or "listings" not in d:
                raise ValueError("JSON 里没有 listings（接口变了）")
        except (FetchError, ValueError) as e:
            return StoreResult(store=sid, ok=False, error=f"搜索失败：{e}")
        for l in d["listings"]:
            title = clean(l.get("title") or "")
            desc = clean(l.get("description") or "")
            pid = str(l.get("itemId") or "")
            ok, via_body = hiangle_match(title, desc)
            if not pid or pid in res.products_checked or not ok:
                continue
            reserved = bool(l.get("reserved")) or is_reserved(title)
            res.products_checked.add(pid)
            attrs = {a.get("key"): a.get("value") for a in l.get("attributes") or []}
            ctxt = str(attrs.get("condition") or "")
            plat = _COND.get(ctxt.strip().lower())
            pi = l.get("priceInfo") or {}
            ptype = pi.get("priceType", "")
            price = pi["priceCents"] / 100 if ptype in ("FIXED", "MIN_BID") and pi.get("priceCents") else None
            raw, uk = size_from_text(title, desc)
            res.obs.append(Obs(
                store=sid, product_id=pid, title=title, url=base + (l.get("vipUrl") or ""),
                variant_id="1", raw_size=raw or title[:40], uk=uk, color="",
                price=price, currency=cfg.get("currency", "EUR"), status=UNKNOWN if reserved else IN,
                condition=merge_condition(plat, condition_from_text(title, desc)),
                note=f"平台成色：{ctxt or '无'}；价格类型 {ptype}{'（起拍价）' if ptype == 'MIN_BID' else ''}；"
                     f"{(l.get('location') or {}).get('cityName', '')}"
                     + ("；已预订（gereserveerd）" if reserved else "")
                     + ("；型号仅见于描述，标题未写 Hiangle" if via_body else ""),
            ))
    return finish(res, cfg)
