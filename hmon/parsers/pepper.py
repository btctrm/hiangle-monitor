"""Pepper 平台折扣社区（Dealabs / mydealz / hotukdeals / Pepper.pl / Chollometro / Preisjäger）。

搜索页 https://<domain>/search?q=<q> 是服务器渲染 HTML（普通 GET 即可）：
  - 每条帖子在 data-vue3='{"name":"ThreadMainListItemNormalizer","props":{"thread":{...}}}' 里，
    thread: threadId / title / titleSlug / isExpired / status / type / price / nextBestPrice /
    merchant.merchantName / linkHost / shareableLink / publishedAt。
  - 搜索命中数在 "pagination":{...,"items":N,"routeName":"search"}。N=0 时页面会塞几条无关的“推荐帖”，
    所以一律再按标题过滤 hiangle。
Dealabs 搜 "hiangle" 搜不到标题写 "Hi-angle" 的帖子，所以默认同时搜 "hi angle"；
还可加 "five ten"（结果仍按标题过滤）。每个关键词 1 次请求（默认 3 次）。

建模：一条帖子 = 一条 listing（variant_id "1"），已过期/已删除/endDate 已过 → OUT；
未过期且发布在 max_age_days（默认 30）内 → IN；未过期但更老（或无发布时间）→ UNKNOWN（老帖常没人标过期）；
帖子标题里的尺码多是范围（"Tailles 44 à 50 2/3"），不猜，只认 to_uk(AUTO) 能确定的单一尺码。
价格 = 帖子 price（社区填写的成交价），币种按 cfg.currency（页面不带币种）。

cfg：domain, currency, searches（默认 [hiangle, "hi angle", "five ten"]）
"""
from __future__ import annotations

import html as htmllib
import json
import re
import time
import urllib.parse

from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch
from ..sizes import gender_from_title, to_uk

_HI = re.compile(r"\bhi[\s\-]?angle|ハイアングル|하이앵글", re.I)
_VUE = re.compile(r"data-vue3='([^']*)'")
_PAGI = re.compile(r'"items":(\d+),"routeName":"search"')


def _threads(page: str) -> list[dict]:
    out = []
    for m in _VUE.finditer(page):
        raw = m.group(1)
        if "ThreadMainListItemNormalizer" not in raw:
            continue
        try:
            d = json.loads(htmllib.unescape(raw))
        except ValueError:
            continue
        t = ((d.get("props") or {}).get("thread")) or {}
        if t.get("threadId"):
            out.append(t)
    return out


def _ts(v) -> float | None:
    """publishedAt 是整数秒；endDate/startDate 是 {"timestamp": 秒}。"""
    if isinstance(v, dict):
        v = v.get("timestamp")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _thread_url(page: str, domain: str, t: dict) -> str:
    tid, slug = str(t["threadId"]), t.get("titleSlug") or ""
    if slug:
        m = re.search(r"https://" + re.escape(domain) + r"/[a-z\-]+/" + re.escape(slug) + "-" + tid + r"\b", page)
        if m:
            return m.group(0)
    return t.get("shareableLink") or f"https://{domain}/share-deal/{tid}"


def scan(cfg: dict) -> StoreResult:
    sid = cfg["id"]
    domain = cfg["domain"]
    cur = cfg.get("currency", "EUR")
    res = StoreResult(store=sid, ok=True)
    max_age = float(cfg.get("max_age_days", 30))
    now = time.time()
    seen: dict[str, tuple[dict, str]] = {}
    for q in cfg.get("searches", ["hiangle", "hi angle", "five ten"]):
        url = f"https://{domain}/search?q={urllib.parse.quote_plus(q)}"
        try:
            page = fetch(url)
        except FetchError as e:
            return StoreResult(store=sid, ok=False, error=f"搜索 {q!r} 失败：{e}")
        pm = _PAGI.search(page)
        if not pm:
            return StoreResult(store=sid, ok=False, error=f"搜索 {q!r}：找不到 pagination（可能改版或被拦截）")
        threads = _threads(page)
        if int(pm.group(1)) > 0 and not threads:
            return StoreResult(store=sid, ok=False, error=f"搜索 {q!r}：命中 {pm.group(1)} 条但解析不到帖子（结构变了）")
        if int(pm.group(1)) == 0:
            continue  # 0 命中时页面里的帖子是无关推荐
        for t in threads:
            tid = str(t["threadId"])
            if tid in seen or not _HI.search(t.get("title") or ""):
                continue
            if (t.get("type") or "Deal") == "Discussion":
                continue
            seen[tid] = (t, _thread_url(page, domain, t))

    for tid, (t, turl) in seen.items():
        title = t.get("title") or ""
        merchant = ((t.get("merchant") or {}).get("merchantName")) or t.get("linkHost") or "?"
        expired = bool(t.get("isExpired")) or bool(t.get("deletedAt")) or (t.get("status") not in (None, "Activated"))
        end_ts = _ts(t.get("endDate"))
        if end_ts and end_ts < now:
            expired = True  # 帖子写了截止时间且已过
        pub_ts = _ts(t.get("publishedAt"))
        age_days = (now - pub_ts) / 86400 if pub_ts else None
        # 社区常常忘了把老帖标过期：未过期但发布超过 max_age_days（或无发布时间）→ UNKNOWN，不报有货
        stale = not expired and (age_days is None or age_days > max_age)
        status = OUT if expired else (UNKNOWN if stale else IN)
        uk = to_uk(title, "AUTO", gender_from_title(title))
        price = t.get("price")
        try:
            price = float(price) if price not in (None, "", 0) else None
        except (TypeError, ValueError):
            price = None
        res.products_checked.add(tid)
        res.obs.append(Obs(
            store=sid, product_id=tid, title=f"{title} @ {merchant}", url=turl, variant_id="1",
            raw_size=title if uk is not None else "", uk=uk, color="", price=price, currency=cur,
            status=status, condition="new",
            note=(f"折扣帖（{merchant}，{t.get('linkHost') or ''}）{'已过期' if expired else ('未过期但已是老帖，状态不明' if stale else '未过期')}；"
                  f"尺码见帖子/商家页，价格为帖子填写价"),
        ))
    for k in cfg.get("_known_products", []):
        if k not in seen:
            res.gone_products.add(k)
    return res
