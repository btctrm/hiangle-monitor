"""汇率与利润计算。"""
from __future__ import annotations

import requests

# 取不到实时汇率时的兜底值（1 单位外币 = 多少人民币），推送里会注明“汇率为兜底值”
FALLBACK = {"CNY": 1.0, "USD": 7.2, "EUR": 8.0, "GBP": 9.5, "CAD": 5.2, "JPY": 0.049, "AUD": 4.7, "CHF": 8.6,
            "SEK": 0.68, "NOK": 0.68, "DKK": 1.07, "PLN": 1.9, "CZK": 0.31, "HUF": 0.02,
            "HKD": 0.92, "SGD": 5.5, "TWD": 0.22, "KRW": 0.0052, "NZD": 4.3}

_cache: dict = {}


def rates() -> tuple[dict, bool]:
    """返回 (外币→人民币汇率表, 是否实时)。"""
    if _cache:
        return _cache["r"], _cache["live"]
    try:
        d = requests.get("https://open.er-api.com/v6/latest/CNY", timeout=20).json()
        if d.get("result") != "success":
            raise ValueError(d)
        r = {k: 1 / v for k, v in d["rates"].items() if v}
        _cache.update(r=r, live=True)
    except Exception:
        _cache.update(r=dict(FALLBACK), live=False)
    return _cache["r"], _cache["live"]


TIER_RANK = {None: 0, "record": 1, "unknown_size": 2, "cold": 2, "normal": 3, "strong": 4}
PUSH_TIERS = {"unknown_size", "cold", "normal", "strong"}
TIER_LABEL = {
    "strong": "【好价】",
    "normal": "",
    "cold": "【冷门码】",
    "unknown_size": "【码制不明】",
    "record": "",
}


def evaluate(obs, store_cfg: dict, cfg: dict) -> dict:
    """算到手成本、利润和推送档位。"""
    p = cfg["profit"]
    r, live = rates()
    rate = r.get(obs.currency)
    if obs.price is None or rate is None:
        return {"tier": None, "landed": None, "profit": None, "fx_live": live, "error": f"无法换算 {obs.currency}"}
    ship = float(store_cfg.get("shipping", 0))
    landed = (obs.price + ship) * rate * (1 + p["fx_fee"])
    forwarder = p["forwarder"].get(store_cfg.get("region", ""), p["forwarder"]["default"])
    cond = getattr(obs, "condition", "new")
    # 二手 / 近新按二手售价算利润；二手平台上成色不明的也按二手算（保守）
    second = cond in ("used", "like_new") or (cond == "unknown" and (store_cfg.get("segment") == "used" or store_cfg.get("unknown_as_used")))
    sale = p.get("used_sale_price", p["sale_price"]) if second else p["sale_price"]
    profit = sale - p["domestic_post"] - forwarder - landed
    t = cfg["thresholds"]
    lo, hi = t["core_uk"]
    if obs.uk is None:
        tier = "unknown_size" if landed <= t["normal"] else "record"
    elif lo <= obs.uk <= hi:
        tier = "strong" if landed <= t["strong"] else "normal" if landed <= t["normal"] else "record"
    else:
        tier = "cold" if landed <= t["cold"] else "record"
    min_profit = cfg.get("rules", {}).get("min_profit")
    if min_profit is not None and tier in PUSH_TIERS and profit < float(min_profit):
        tier = "record"  # 利润太薄：只进日报
    if cond == "used" and not cfg.get("rules", {}).get("push_used", True) and tier in PUSH_TIERS:
        tier = "record"  # 关掉二手推送时：二手只进日报
    return {
        "tier": tier,
        "landed": round(landed),
        "profit": round(profit),
        "forwarder": forwarder,
        "sale": sale,
        "shipping": ship,
        "rate": rate,
        "fx_live": live,
    }
