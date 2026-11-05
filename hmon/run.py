"""主流程：扫描所有店铺 → 与上次状态对比 → 两次确认 → 推送 / 日报。

推送条件（全部满足才推）：
  1. 店铺本轮抓取正常（被拦截、改版、字段缺失 → 整店“未知”，不动任何尺码状态）
  2. 该尺码连续 >= confirm_runs 次成功检测都是“有货”，且档位不低于上次推送的档位
  3. 档位（按到手成本算）比上次推送更好：缺货→有货、新上架、降价跨档都算
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import notify
from .core import IN, OUT, UNKNOWN, Obs, StoreResult
from .money import PUSH_TIERS, TIER_LABEL, TIER_RANK, evaluate, rates
from .parsers import bergfreunde, ebay, japan, jsonld, poshmark, shopify
import html as _h

from .sizes import eu_of, fmt_uk, size_line, size_short

ROOT = Path(__file__).resolve().parent.parent
BJ = timezone(timedelta(hours=8))
PARSERS = {"shopify": shopify, "bergfreunde": bergfreunde, "jsonld": jsonld, "ebay": ebay, "japan": japan, "poshmark": poshmark}
COND_LABEL = {"used": "【二手】", "unknown": "【成色未知】", "new": "", "like_new": "【近新】"}
CUR = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$", "JPY": "JP¥", "CNY": "¥"}


def now_bj() -> datetime:
    return datetime.now(BJ)


def ts(dt: datetime | None = None) -> str:
    return (dt or now_bj()).strftime("%Y-%m-%d %H:%M")


def load_cfg() -> dict:
    """config.yaml + config.d/*.yaml（后者只合并 stores 和 ignore）。"""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg.setdefault("stores", [])
    for p in sorted((ROOT / "config.d").glob("*.yaml")):
        extra = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg["stores"] += extra.get("stores") or []
        cfg.setdefault("ignore", [])
        cfg["ignore"] = (cfg["ignore"] or []) + (extra.get("ignore") or [])
    ids = [s["id"] for s in cfg["stores"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise SystemExit(f"店铺 id 重复：{dup}")
    return cfg


def parser_for(kind: str):
    if kind in PARSERS:
        return PARSERS[kind]
    return importlib.import_module(f".parsers.{kind}", __package__)


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"variants": {}, "stores": {}, "meta": {}}


def save_state(path: Path, st: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def money(v, cur):
    return f"{CUR.get(cur, cur + ' ')}{v:,.2f}" if v is not None else "?"


def size_text(o: dict, scfg: dict) -> str:
    """推送里的尺码行。认得出：欧码/UK/美码 + 店铺原文；认不出：店铺原文 + 推测（仅供参考，不参与判断）。"""
    raw = o.get("raw_size", "")
    if o.get("uk") is not None:
        guess = "，换算按店铺码制推测" if scfg.get("size_verified") is False else ""
        return f"{size_line(o['uk'], raw)}（店铺写“{raw}”{guess}）"
    from .sizes import gender_from_title, to_uk

    g = gender_from_title(o.get("title", ""))
    hints = []
    for system, label in (("US_W", "美码女"), ("US_M", "美码男")) if g == "W" else (("US_M", "美码男"), ("US_W", "美码女")):
        uk = to_uk(raw, system)
        if uk is not None and len(raw) <= 5:
            hints.append(f"若是{label} {raw} ≈ UK {uk:g} / EU {eu_of(uk)}")
    uk = to_uk(raw, "EU") if len(raw) <= 7 else None
    if uk is not None:
        hints.append(f"若是欧码 {raw} ≈ UK {uk:g}")
    hint = "；".join(hints[:2])
    return f"码制不明，店铺写“{raw[:40]}”" + (f"（{hint}，仅供参考，请看商品页）" if hint else "（请看商品页）")


def alert_text(o: dict, ev: dict, scfg: dict, first_seen: str, note: str) -> tuple[str, str]:
    tier = ev["tier"]
    uk = fmt_uk(o["uk"])
    title = (
        f"{TIER_LABEL.get(tier, '')}{COND_LABEL.get(o['condition'], '')}"
        f"{o['title'][:40]} {size_short(o['uk'], o['raw_size'])} 到手¥{ev['landed']} · {scfg['name']}"
    )
    cond_text = {"new": "全新", "like_new": "近新（平台或卖家标注），请看图确认", "used": "二手，请看图确认磨损",
                 "unknown": "未知，请看图确认"}.get(o["condition"], o["condition"])
    lines = [
        f"### {TIER_LABEL.get(tier, '')}{COND_LABEL.get(o['condition'], '')}{o['title']}",
        f"- **尺码**：{size_text(o, scfg)}",
        f"- **到手成本**：约 ¥{ev['landed']}{'' if ev['fx_live'] else '（汇率为兜底值）'}"
        f" · **预估利润**：约 ¥{ev['profit']}（售价 {ev.get('sale', 1050):g}{'，按二手价' if ev.get('sale', 1050) != 1050 else ''} − 转运 ¥{ev['forwarder']:g} − 国内邮费 10）",
        f"- **标价**：{money(o['price'], o['currency'])}，店铺运费估 {money(ev['shipping'], o['currency'])}",
        f"- **成色**：{cond_text}",
    ]
    if o.get("note"):
        lines.append(f"- **备注**：{o['note']}")
    lines.append(f"- **链接**：{o['url']}")
    lines += [
        f"- **店铺 / 配色**：{scfg['name']}（{scfg.get('region', '')}） / {o['color'] or '—'}",
        f"- **检测**：首次 {first_seen}，确认 {ts()}（北京时间）" + (f"；{note}" if note else ""),
    ]
    return title, "\n".join(lines)


def is_ignored(cfg: dict, store: str, product_id: str, variant_id: str = "") -> bool:
    """config.yaml 里 ignore 列表：你看过觉得不要的商品，不再推送、不进日报。"""
    for it in cfg.get("ignore") or []:
        if it.get("store") != store:
            continue
        if it.get("product") and it["product"] != product_id:
            continue
        if it.get("variant") and str(it["variant"]) != str(variant_id):
            continue
        return True
    return False


def migrate_baseline(st: dict) -> None:
    """一次性修正：旧版本把“首次扫描时就已达标”的商品记成已推送，其实从没推过。改成待推。"""
    if st["meta"].get("migr_baseline_v1"):
        return
    st["meta"]["migr_baseline_v1"] = True
    for v in st["variants"].values():
        base_at = st["stores"].get(v.get("store"), {}).get("baseline_at")
        if (v.get("status") == IN and v.get("tier") in PUSH_TIERS and v.get("notified_tier") == v.get("tier")
                and not v.get("notified_at") and base_at and (v.get("first_in") or "") <= base_at):
            v["notified_tier"] = None
            v["baseline_carry"] = True


def limit_of(cfg: dict, uk) -> int:
    """这个尺码适用的推送门槛（到手成本上限）。"""
    t = cfg["thresholds"]
    lo, hi = t["core_uk"]
    if uk is None:
        return t["normal"]
    return t["normal"] if lo <= uk <= hi else t["cold"]


def track_price(v: dict, price, cfg: dict, drops: dict, o, baselined: bool) -> None:
    """记录价格变化。连续两轮价格一致（±2%）才算真实价格，避免页面刷新时价格跳动造成误报。"""
    if price is None:
        return
    last = v.get("price_last")
    v["price_last"] = price
    if last is None or abs(price - last) > 0.02 * max(price, last):
        return
    conf = max(price, last)  # 两轮里较高的那个，保守
    ref = v.get("price_ref")
    if ref is not None and abs(conf - ref) <= 0.02 * ref:
        return
    hist = v.setdefault("price_hist", [])
    hist.append([ts(), conf])
    del hist[:-20]
    pct = float(cfg["rules"].get("price_drop_pct", 10))
    if ref is not None and baselined and pct > 0 and conf < ref * (1 - pct / 100):
        drops.setdefault((o.store, o.product_id, o.color, ref, conf), []).append(v)
    v["price_ref"] = conf


def drop_alerts(cfg: dict, st: dict, drops: dict, now: str) -> list[tuple[str, str]]:
    """把同一商品同一次降价的所有尺码合成一条。"""
    stores = {s["id"]: s for s in cfg["stores"]}
    lo, hi = cfg["thresholds"]["core_uk"]
    msgs, events = [], st["meta"].setdefault("price_drops", [])
    for (sid, pid, color, old, new), vs in drops.items():
        vs = [v for v in vs if v.get("notified_at") != now]  # 本轮已经按门槛推过的不重复推
        if not vs:
            continue
        v0 = vs[0]
        scfg = stores.get(sid, {})
        pct = round((1 - new / old) * 100)
        core = [v for v in vs if v.get("uk") is None or lo <= v["uk"] <= hi]
        best = min((v.get("landed") or 9e9) for v in vs)
        sizes = "、".join(size_short(v.get("uk"), v.get("raw_size", "")) for v in sorted(vs, key=lambda x: x.get("uk") or 99))
        events.append({"time": now, "store": sid, "title": v0.get("title", ""), "color": color, "old": old, "new": new,
                       "currency": v0.get("currency", ""), "pct": pct, "landed": best, "n": len(vs), "url": v0.get("url", "")})
        if not cfg["rules"].get("price_drop_push", True) or not core:
            continue  # 只有冷门码降价：只进日报
        gap = best - min(limit_of(cfg, v.get("uk")) for v in core)
        title = f"【降价 -{pct}%】{v0.get('title', '')[:36]} {money(new, v0.get('currency', ''))} · {scfg.get('name', sid)}"
        body = "\n".join([
            f"### {title}",
            f"- **价格**：{money(old, v0.get('currency', ''))} → {money(new, v0.get('currency', ''))}（-{pct}%）",
            f"- **配色**：{color or '—'}",
            f"- **有货尺码**：{sizes}",
            f"- **最低到手成本**：约 ¥{best}，{'已达到推送门槛' if gap <= 0 else f'离门槛还差 ¥{gap}'}",
            "- **说明**：价格连续两轮确认；还没到门槛的降价也提醒，方便你判断是不是在打折",
            f"- **链接**：{v0.get('url', '')}",
        ])
        msgs.append((title, body))
    del events[:-30]
    if len(msgs) > 3:
        return [(f"【{len(msgs)} 个商品降价】Hiangle 监控", "\n\n---\n\n".join(b for _, b in msgs))]
    return msgs


def note_notify_errors(st: dict, errors: list[str], now: str, dry: bool) -> None:
    """通知渠道出错：记进日报；每天最多单独提醒一次（能用的渠道会收到）。"""
    if dry or not errors:
        return
    meta = st["meta"]
    meta["notify_error"] = {"time": now, "errors": sorted(set(errors))[:5]}
    if meta.get("notify_error_day") != now[:10]:
        meta["notify_error_day"] = now[:10]
        notify.send("【通知渠道异常】Hiangle 监控",
                    "以下通知渠道发送失败，收不到推送的话请检查对应的 Token / 邮箱授权码：\n\n"
                    + "\n".join(f"- {e}" for e in sorted(set(errors))) + f"\n\n时间：{now}\n\n没发出去的上新提醒会在下一轮自动重发。")


def scan_store(scfg: dict, st: dict) -> StoreResult:
    known = sorted({v["product_id"] for k, v in st["variants"].items() if v["store"] == scfg["id"]})
    cfg2 = dict(scfg, _known_products=known)
    from . import core

    core.LIMITS.update(timeout=15, retries=0) if scfg.get("trial") else core.LIMITS.update(timeout=25, retries=2)
    try:
        return parser_for(scfg["type"]).scan(cfg2)
    except Exception as e:  # 解析器自身出错：整店未知
        return StoreResult(store=scfg["id"], ok=False, error=f"解析器异常：{e.__class__.__name__}: {e}")
    finally:
        core.LIMITS.update(timeout=25, retries=2)


def run(dry: bool = False, only: str | None = None, state_path: Path | None = None) -> int:
    cfg = load_cfg()
    state_path = state_path or ROOT / "state" / "state.json"
    st = load_state(state_path)
    st.setdefault("meta", {})
    now = ts()
    confirm_runs = int(cfg["rules"]["confirm_runs"])
    alerts: list[tuple[str, str, list]] = []  # (标题, 正文, [(尺码记录, 推送前的档位)])
    health_msgs: list[tuple[str, str]] = []
    drops: dict = {}  # 明显降价：(店, 商品, 配色, 旧价, 新价) -> 尺码列表
    migrate_baseline(st)
    run_log = {"time": now, "stores": {}}

    for scfg in cfg["stores"]:
        if not scfg.get("enabled", True) or (only and scfg["id"] != only):
            continue
        sid = scfg["id"]
        ss = st["stores"].setdefault(sid, {"fail": 0, "alerted": False, "baseline": False})
        every = int(scfg.get("every_minutes", 0))  # 比价站 / 二手平台不用每轮都查，免得被封
        if every and ss.get("last_scan") and not only:
            last = datetime.strptime(ss["last_scan"], "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
            if now_bj() - last < timedelta(minutes=every - 2):
                run_log["stores"][sid] = f"跳过（每 {every} 分钟查一次）"
                continue
        ss["last_scan"] = now
        res = scan_store(scfg, st)
        mine = {k: v for k, v in st["variants"].items() if v["store"] == sid}

        if not res.ok:
            ss["fail"] += 1
            ss["last_error"] = res.error
            run_log["stores"][sid] = f"失败：{res.error}"
            for v in mine.values():  # 失败会打断连续确认
                v["streak"] = 0
            if ss["fail"] >= cfg["rules"]["fail_alert_after"] and not ss["alerted"] and not scfg.get("trial"):
                ss["alerted"] = True
                health_msgs.append((f"【监控失效】{scfg['name']}", f"连续 {ss['fail']} 次抓取失败，这家店的尺码状态现在一律按“未知”处理，不会推有货。\n\n最近错误：{res.error}\n\n时间：{now}"))
            continue

        if ss.get("alerted") and not scfg.get("trial"):
            health_msgs.append((f"【监控恢复】{scfg['name']}", f"已恢复正常抓取。时间：{now}"))
        ss.update(fail=0, alerted=False, last_ok=now, last_error="")
        if res.error:  # 例如 eBay 未配置密钥
            run_log["stores"][sid] = res.error
            continue

        # —— 异常突变保护：大量尺码同时从缺货变有货，多半是页面/解析出问题 ——
        #    第一次出现时作废本轮并提醒；下一轮仍是同一批尺码变有货，才认为是真的整批补货，
        #    之后仍要再走一遍“连续两次确认”才会推。
        flip_keys = sorted(o.key for o in res.obs if o.status == IN and mine.get(o.key, {}).get("status") == OUT)
        tracked = sum(1 for o in res.obs if o.key in mine)
        mass = ss["baseline"] and len(flip_keys) >= 5 and tracked and len(flip_keys) / tracked >= 0.8
        sig = hashlib.sha1("\n".join(flip_keys).encode()).hexdigest()[:12]  # 跨进程稳定
        if mass and ss.get("anomaly") != sig:
            ss["anomaly"], ss["anomaly_left"] = sig, 3
            run_log["stores"][sid] = f"异常：{len(flip_keys)}/{tracked} 个尺码同时变有货，本轮作废"
            health_msgs.append((f"【监控异常】{scfg['name']}", f"本轮 {len(flip_keys)}/{tracked} 个尺码同时从缺货变有货，可能是整批补货，也可能是页面或解析出错。本轮结果作废、不推送；下一轮若仍一致，再按正常流程确认后推送。请人工看一眼：{scfg.get('home', '')}\n\n时间：{now}"))
            for v in mine.values():
                v["streak"] = 0
            continue

        seen = set()
        n_in = n_unknown = 0
        res.obs = [o for o in res.obs if not is_ignored(cfg, sid, o.product_id, o.variant_id)]
        for k in [k for k, v in st["variants"].items() if v["store"] == sid and is_ignored(cfg, sid, v["product_id"], k.split("|")[-1])]:
            st["variants"].pop(k)
            mine.pop(k, None)
        for o in res.obs:
            seen.add(o.key)
            v = st["variants"].get(o.key)
            d = o.to_dict()
            if v is None:
                v = {"streak": 0, "notified_tier": None, "status": None, "first_in": None}
                st["variants"][o.key] = v
            prev_status = v.get("status")
            v.update({k: d[k] for k in ("store", "product_id", "title", "url", "raw_size", "uk", "color", "price", "currency", "condition", "note")})
            v["last_seen"] = now

            if o.status == UNKNOWN:
                n_unknown += 1
                v["streak"] = 0  # 不确定就不累积确认次数，也不改状态
                continue
            if o.status == OUT:
                v.update(status=OUT, streak=0, notified_tier=None, first_in=None, tier=None)
                continue

            n_in += 1
            ev = evaluate(o, scfg, cfg)
            prev_tier = v.get("tier")
            # 连续确认按“档位”算：上一轮档位不低于本轮，才算本轮价格被复查过
            if prev_status == IN and v.get("streak", 0) > 0 and TIER_RANK.get(prev_tier, 0) >= TIER_RANK.get(ev["tier"], 0):
                v["streak"] = v.get("streak", 0) + 1
            else:
                v["streak"] = 1
            v["landed"], v["profit"], v["tier"] = ev["landed"], ev["profit"], ev["tier"]
            if prev_status != IN:
                v["first_in"] = now
            v["status"] = IN

            track_price(v, o.price, cfg, drops, o, ss["baseline"])
            if not ss["baseline"]:  # 第一次扫这家店：当前库存记为基线，不算“上新”
                # 达到推送门槛的除外：首次扫描就已在库的好货也要推一次（复查后）
                v["notified_tier"] = ev["tier"] if ev["tier"] not in PUSH_TIERS else None
                if ev["tier"] in PUSH_TIERS:
                    v["baseline_carry"] = True
                continue
            tier = ev["tier"]
            if tier not in PUSH_TIERS or TIER_RANK[tier] <= TIER_RANK.get(v.get("notified_tier"), 0):
                continue
            if v["streak"] < int(scfg.get("confirm_runs", confirm_runs)):
                continue  # 等下一轮复查（二手/比价站一条 listing 出现即算，confirm_runs: 1）
            if o.condition not in cfg["rules"].get("push_conditions", ["new", "like_new", "used", "unknown"]):
                continue  # 有使用痕迹的二手不推（只进日报）
            if tier == "unknown_size" and not scfg.get("push_unknown_size", scfg.get("segment") != "aggregator"):
                continue  # 比价站“码制不明”的条目太多：只进日报
            notes = []
            if ss.get("anomaly"):
                notes.append("该店刚出现过大面积同时上新，请重点核实")
            if v.pop("baseline_carry", None):
                notes.append("首次扫描这家店时就已在库，之前没推过")
            if scfg.get("trial"):
                notes.append("试运行店铺，解析未经人工验收，请打开链接核实")
            if v.get("retry"):
                notes.append(f"上次推送失败，第 {v['retry'] + 1} 次重发")
            alerts.append((*alert_text(d, ev, scfg, v["first_in"] or now, "；".join(notes)), [(v, v.get("notified_tier"))]))
            v["notified_tier"] = tier
            v["notified_at"] = now

        # 商品下架 / 尺码从列表消失：按缺货处理（只针对本轮确实检查过或确认 404 的商品）
        for k, v in mine.items():
            if k in seen:
                continue
            if v["product_id"] in res.products_checked or v["product_id"] in res.gone_products:
                v.update(status=OUT, streak=0, notified_tier=None, first_in=None, tier=None)
        if ss.get("anomaly") and not mass:
            ss["anomaly_left"] = ss.get("anomaly_left", 1) - 1
            if ss["anomaly_left"] <= 0:
                ss.pop("anomaly", None)
                ss.pop("anomaly_left", None)
        if not ss["baseline"]:
            ss["baseline"] = True
            ss["baseline_at"] = now
        run_log["stores"][sid] = f"正常：{len(res.obs)} 个尺码，{n_in} 有货，{n_unknown} 未知"

    # 清理 30 天没见过的缺货记录
    cutoff = ts(now_bj() - timedelta(days=30))
    st["variants"] = {k: v for k, v in st["variants"].items() if v.get("status") == IN or v.get("last_seen", now) >= cutoff}

    # —— 明显降价（没到推送门槛也提醒，黑五/清仓时最有用）——
    drop_msgs = drop_alerts(cfg, st, drops, now)

    # —— 发送 ——
    #    推送失败（所有渠道都没发出去）：不记为“已推送”，下一轮自动重发。
    batches = []
    if len(alerts) > cfg["rules"]["max_separate_alerts"]:
        body = "\n\n---\n\n".join(b for _, b, _ in alerts)
        batches.append((f"【{len(alerts)} 条上新/降价】Hiangle 监控", body, [x for _, _, refs in alerts for x in refs]))
    else:
        batches += alerts
    errors = []
    for t, b, refs in batches:
        res = notify.send(t, b, dry=dry)
        errors += notify.failures(res)
        if not notify.delivered(res):
            for v, prev in refs:  # 回滚：下一轮重发
                v["notified_tier"] = prev
                v.pop("notified_at", None)
                v["retry"] = v.get("retry", 0) + 1
        else:
            for v, _ in refs:
                v.pop("retry", None)
    for t, b in drop_msgs + health_msgs:
        errors += notify.failures(notify.send(t, b, dry=dry))
    note_notify_errors(st, errors, now, dry)

    st["meta"]["last_run"] = now
    st["meta"]["runs_today"] = st["meta"].get("runs_today", 0) + 1 if st["meta"].get("runs_day") == now[:10] else 1
    st["meta"]["runs_day"] = now[:10]
    st["meta"]["last_log"] = run_log
    maybe_digest(cfg, st, dry)
    save_state(state_path, st)
    print(json.dumps(run_log, ensure_ascii=False, indent=1))
    print(f"本轮推送 {len(alerts)} 条，健康提醒 {len(health_msgs)} 条")
    return 0


def _cost_row(v: dict) -> dict:
    return {
        "eu": eu_of(v["uk"]) if v["uk"] is not None else "?",
        "uk": f"{v['uk']:g}" if v["uk"] is not None else "?",
        "usm": f"{v['uk'] + 0.5:g}" if v["uk"] is not None else "?",
        "raw": v.get("raw_size", ""),
        "price": money(v.get("price"), v.get("currency", "")),
        "landed": v.get("landed"),
        "profit": v.get("profit"),
        "cond": {"new": "全新", "like_new": "近新", "used": "二手", "unknown": "成色未知"}.get(v.get("condition"), "?"),
        "tier": TIER_LABEL.get(v.get("tier"), "") or ("达标" if v.get("tier") in PUSH_TIERS else ""),
        "title": v.get("title", ""),
        "color": v.get("color", ""),
        "url": v.get("url", ""),
    }


def digest_text(cfg: dict, st: dict) -> tuple[str, str, str]:
    """日报：返回 (标题, 纯文本, HTML)。每个有货尺码都列出欧码、价格、到手成本、利润。"""
    stores = {s["id"]: s for s in cfg["stores"]}
    failing = {sid for sid, ss in st["stores"].items() if ss.get("fail", 0) > 0}
    rows = [v for v in st["variants"].values()
            if v.get("status") == IN and v.get("landed") is not None and v["store"] not in failing]
    rows.sort(key=lambda v: (-TIER_RANK.get(v.get("tier"), 0), v["landed"]))
    _, live = rates()
    good = [v for v in rows if v.get("tier") in PUSH_TIERS]
    # 离门槛最近：同一家店同一款同一价格的尺码合并成一行
    groups: dict = {}
    for v in rows:
        if v.get("tier") in PUSH_TIERS:
            continue
        g = groups.setdefault((v["store"], v.get("title"), v.get("color"), v["landed"], limit_of(cfg, v.get("uk"))), [])
        g.append(v)
    near = sorted(groups.values(), key=lambda g: min(v["landed"] - limit_of(cfg, v.get("uk")) for v in g))[:5]

    def near_line(g):
        g = sorted(g, key=lambda v: v.get("uk") if v.get("uk") is not None else 99)
        v = min(g, key=lambda v: v["landed"] - limit_of(cfg, v.get("uk")))
        lim = limit_of(cfg, v.get("uk"))
        sizes = "、".join((f"UK {x['uk']:g}" if x.get("uk") is not None else f"码制不明（{x.get('raw_size', '')}）") for x in g)
        return v, lim, sizes
    week_ago = ts(now_bj() - timedelta(days=7))
    recent_drops = [e for e in st["meta"].get("price_drops", []) if e.get("time", "") >= week_ago][::-1]
    nerr = st["meta"].get("notify_error")
    def sname(sid):
        s = stores.get(sid, {})
        return s.get("name", sid) + ("（试运行）" if s.get("trial") else "")
    now = ts()
    title = f"Hiangle 日报 {now[:10]}：{len(good)} 个达标 / {len(rows)} 个有货"

    # ---------- 纯文本 ----------
    t = [f"Hiangle 日报 {now}（北京时间）", f"当前有货 {len(rows)} 个尺码，达到推送门槛 {len(good)} 个。{'' if live else '（汇率为兜底值）'}", "", "【达到门槛】"]
    for v in good:
        r = _cost_row(v)
        t.append(f"- {r['tier']}{COND_LABEL.get(v['condition'], '')}{size_short(v['uk'], v['raw_size'])} 到手¥{r['landed']} 利润≈¥{r['profit']} · {stores.get(v['store'], {}).get('name', v['store'])} · {r['title'][:40]} · {r['url']}")
    if not good:
        t.append("- 暂无")
    t += ["", "【离门槛最近】（没达标的有货尺码里，到手成本最接近门槛的）"]
    for g in near:
        v, lim, sizes = near_line(g)
        t.append(f"- 到手¥{v['landed']}，门槛 ¥{lim}，还差 ¥{v['landed'] - lim} · {sname(v['store'])} · {v.get('title', '')[:36]} · 尺码 {sizes} · {v.get('url', '')}")
    if not near:
        t.append("- 暂无")
    t += ["", "【近 7 天明显降价】"]
    for e in recent_drops:
        t.append(f"- {e['time']} {sname(e['store'])} {e['title'][:36]} {e.get('color', '')[:20]}：{money(e['old'], e['currency'])} → {money(e['new'], e['currency'])}（-{e['pct']}%），{e['n']} 个尺码，最低到手¥{e['landed']}")
    if not recent_drops:
        t.append("- 暂无")
    by_store: dict = {}
    for v in rows:
        by_store.setdefault(v["store"], []).append(v)
    # 来源多了以后不再逐码列全部有货尺码（邮件会超过 Gmail 102KB 被截断），改成每个来源一行概况
    t += ["", "【运行情况】", f"- 今天已运行 {st['meta'].get('runs_today', 0)} 次，最近一次 {st['meta'].get('last_run', '-')}"]
    if nerr:
        t.append(f"- 最近一次通知渠道出错：{nerr['time']} {'；'.join(nerr['errors'])}")
    active = [sid for sid in st["stores"] if sid in stores and stores[sid].get("enabled", True)]
    active.sort(key=lambda x: (-(st["stores"][x].get("fail", 0) > 0), stores[x].get("segment", "retail"), x))

    def store_state(sid):
        ss = st["stores"][sid]
        if ss.get("fail", 0):
            return True, f"失败 {ss['fail']} 次：{ss.get('last_error', '')[:80]}"
        return False, st["meta"].get("last_log", {}).get("stores", {}).get(sid, "正常")
    for sid in active:
        vs = by_store.get(sid, [])
        low = min((v["landed"] for v in vs), default=None)
        t.append(f"- {sname(sid)}：{store_state(sid)[1]}；有货 {len(vs)} 个" + (f"，最低到手¥{low}" if low else ""))

    # ---------- HTML ----------
    css_td = ""  # 样式统一放进 <style>，否则每个格子重复一遍，邮件会超过 Gmail 102KB 被截断
    css_th = ""
    head = "".join(f"<th>{x}</th>" for x in ["欧码", "UK", "US男", "店铺原文", "标价", "到手成本", "预估利润", "成色", "款式 / 配色", "链接"])

    def tr(v, hl=False):
        r = _cost_row(v)
        bg = "background:#fff6d6;" if hl else ""
        cells = [f"<b>{_h.escape(r['eu'])}</b>", r["uk"], r["usm"], _h.escape(r["raw"]), _h.escape(r["price"]),
                 f"¥{r['landed']}", f"¥{r['profit']}", r["cond"],
                 _h.escape(f"{r['tier']} {r['title'][:38]} · {r['color'][:24]}"),
                 f"<a href='{_h.escape(r['url'])}'>打开</a>"]
        attr = f" style='{bg}'" if bg else ""
        return "<tr>" + "".join(f"<td{attr}>{c}</td>" for c in cells) + "</tr>"

    hp = ["<style>table{border-collapse:collapse}td,th{padding:4px 8px;border-bottom:1px solid #ddd;font-size:13px;"
          "white-space:nowrap;text-align:left}th{background:#f3f3f3}</style>",
          f"<div style='font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222'>",
          f"<h2 style='margin:0 0 4px'>Hiangle 日报</h2><div style='color:#666;font-size:13px'>{now}（北京时间） · 当前有货 {len(rows)} 个尺码，达标 {len(good)} 个{'' if live else ' · 汇率为兜底值'}</div>",
          "<h3>达到门槛</h3>"]
    if good:
        hp.append(f"<table><tr>{head}<th>店铺</th></tr>")
        for v in good:
            hp.append(tr(v, True).replace("</tr>", f"<td>{_h.escape(stores.get(v['store'], {}).get('name', v['store']))}</td></tr>"))
        hp.append("</table>")
    else:
        hp.append("<p>暂无</p>")
    hp.append("<h3>离门槛最近</h3><ul style='font-size:13px'>")
    for g in near:
        v, lim, sizes = near_line(g)
        hp.append(f"<li>到手 <b>¥{v['landed']}</b>，门槛 ¥{lim}，还差 <b>¥{v['landed'] - lim}</b> · "
                  f"{_h.escape(sname(v['store']))} · {_h.escape(v.get('title', '')[:36])} · 尺码 {_h.escape(sizes)} · <a href='{_h.escape(v.get('url', ''))}'>打开</a></li>")
    hp.append("</ul>" if near else "<li>暂无</li></ul>")
    hp.append("<h3>近 7 天明显降价</h3><ul style='font-size:13px'>")
    for e in recent_drops:
        hp.append(f"<li>{e['time']} {_h.escape(sname(e['store']))} {_h.escape(e['title'][:36])}：{_h.escape(money(e['old'], e['currency']))} → "
                  f"<b>{_h.escape(money(e['new'], e['currency']))}</b>（-{e['pct']}%），{e['n']} 个尺码，最低到手 ¥{e['landed']} · <a href='{_h.escape(e.get('url', ''))}'>打开</a></li>")
    hp.append("</ul>" if recent_drops else "<li>暂无</li></ul>")
    seg_cn = {"retail": "新品店", "aggregator": "比价站", "used": "二手", "deals": "折扣站"}
    hp.append(f"<h3>各来源概况</h3><div style='font-size:13px;color:#666'>今天已运行 {st['meta'].get('runs_today', 0)} 次，最近一次 {st['meta'].get('last_run', '-')}</div>")
    if nerr:
        hp.append(f"<div style='font-size:13px;color:#b00'>最近一次通知渠道出错：{nerr['time']} {_h.escape('；'.join(nerr['errors']))}</div>")
    hp.append("<table><tr>" + "".join(f"<th>{x}</th>" for x in ["来源", "类型", "本轮", "有货尺码", "最低到手"]) + "</tr>")
    for sid in active:
        vs = by_store.get(sid, [])
        low = min((v["landed"] for v in vs), default=None)
        bad, state = store_state(sid)
        red = " style='color:#c00'" if bad else ""
        cells = [sname(sid), seg_cn.get(stores[sid].get("segment", "retail"), ""), state, str(len(vs)), f"¥{low}" if low else "-"]
        hp.append("<tr>" + "".join(f"<td{red}>{_h.escape(c)}</td>" for c in cells) + "</tr>")
    hp.append("</table>")
    hp.append("<p style='color:#888;font-size:12px'>到手成本 = (标价 + 店铺运费估算) × 汇率 × 1.015；预估利润 = 售价（全新 1050 / 二手 800）− 国内邮费 − 转运费 − 到手成本；利润低于 ¥150 不推送。黄色行 = 达到推送门槛。</p></div>")
    return title, "\n".join(t), "".join(hp)


def maybe_digest(cfg: dict, st: dict, dry: bool) -> None:
    n = now_bj()
    today = n.strftime("%Y-%m-%d")
    hour = int(cfg["rules"]["digest_hour_bj"])
    first = not st["meta"].get("first_summary_sent")
    if first or (n.hour >= hour and st["meta"].get("last_digest") != today):
        t, b, h = digest_text(cfg, st)
        if first:
            t = "【首次运行】" + t
        sent = notify.send(t, b, wechat=first, email=True, dry=dry, html=h)
        if dry or not notify.delivered(sent):
            return  # 还没配置通知渠道（或演练）：不记为已发送，配好后会补发
        st["meta"]["last_digest"] = today
        st["meta"]["first_summary_sent"] = True


def check(store_id: str) -> int:
    """验收用：打印某家店本轮解析出的每个尺码，拿去和浏览器人工核对。"""
    cfg = load_cfg()
    scfg = next(s for s in cfg["stores"] if s["id"] == store_id)
    res = parser_for(scfg["type"]).scan(dict(scfg, _known_products=[]))
    print(f"{scfg['name']}  ok={res.ok}  {res.error}")
    for o in sorted(res.obs, key=lambda o: (o.title, o.color, o.uk or 0)):
        ev = evaluate(o, scfg, cfg) if o.status == IN else {}
        print(f"  {o.status:7} {fmt_uk(o.uk):8} 原文[{o.raw_size}] {money(o.price, o.currency):>10} "
              f"{('到手¥' + str(ev.get('landed'))) if ev else '':10} {ev.get('tier') or '':12} {o.condition:7} {o.color[:28]:28} {o.title[:36]}  {o.note}")
    return 0


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="hmon", description="Five Ten Hiangle 库存监控")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一轮监控")
    r.add_argument("--dry-run", action="store_true", help="只打印，不发通知、不加购物车")
    r.add_argument("--only", help="只跑某一家店")
    r.add_argument("--state", help="状态文件路径")
    c = sub.add_parser("check", help="验收：打印某家店的逐码解析结果")
    c.add_argument("store")
    sub.add_parser("test-notify", help="发一条测试通知")
    sub.add_parser("digest", help="立即生成日报（只打印）")
    pr = sub.add_parser("probe", help="探测候选店铺能不能读（不改状态、不发通知）")
    pr.add_argument("targets", nargs="+", help="域名（按 Shopify 试）或商品链接；加 --dump 导出页面样本")
    a, extra = ap.parse_known_args(argv)
    if extra and a.cmd != "probe":
        ap.error("未知参数：" + " ".join(extra))
    if a.cmd == "probe":
        a.targets += extra
    if a.cmd == "probe":
        from .probe import probe

        targets = [x for t in a.targets for x in t.replace(",", " ").split()]
        return probe(targets)
    if a.cmd == "run":
        return run(dry=a.dry_run, only=a.only, state_path=Path(a.state) if a.state else None)
    if a.cmd == "check":
        if a.store == "all":
            for s in load_cfg()["stores"]:
                if s.get("enabled", True):
                    try:
                        check(s["id"])
                    except Exception as e:  # 一家出错不影响其他家
                        print(f"{s['id']}  解析器异常：{e}")
            return 0
        return check(a.store)
    if a.cmd == "test-notify":
        notify.send("【测试】Hiangle 监控通知", f"如果你看到这条，说明通知渠道配置成功。\n\n时间：{ts()}")
        return 0
    if a.cmd == "digest":
        cfg = load_cfg()
        st = load_state(ROOT / "state" / "state.json")
        t, b, h = digest_text(cfg, st)
        print(t + "\n" + b)
        if os.environ.get("DIGEST_HTML"):
            Path(os.environ["DIGEST_HTML"]).write_text(h, encoding="utf-8")
        return 0


if __name__ == "__main__":
    sys.exit(main())
