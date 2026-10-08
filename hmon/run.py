"""主流程：扫描所有店铺 → 与上次状态对比 → 两次确认 → 推送 / 日报。

推送条件（全部满足才推）：
  1. 店铺本轮抓取正常（被拦截、改版、字段缺失 → 整店“未知”，不动任何尺码状态）
  2. 该尺码连续 >= confirm_runs 次成功检测都是“有货”，且档位不低于上次推送的档位
  3. 档位（按到手成本算）比上次推送更好：缺货→有货、新上架、降价跨档都算
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import notify
from .core import IN, OUT, UNKNOWN, Obs, StoreResult
from .money import PUSH_TIERS, TIER_LABEL, TIER_RANK, evaluate, rates
from .parsers import bergfreunde, ebay, jsonld, shopify
import html as _h

from .sizes import eu_of, fmt_uk, size_line, size_short

ROOT = Path(__file__).resolve().parent.parent
BJ = timezone(timedelta(hours=8))
PARSERS = {"shopify": shopify, "bergfreunde": bergfreunde, "jsonld": jsonld, "ebay": ebay}
COND_LABEL = {"used": "【二手】", "unknown": "【成色未知】", "new": ""}
CUR = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$", "JPY": "¥", "CNY": "¥"}


def now_bj() -> datetime:
    return datetime.now(BJ)


def ts(dt: datetime | None = None) -> str:
    return (dt or now_bj()).strftime("%Y-%m-%d %H:%M")


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


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


def alert_text(o: dict, ev: dict, scfg: dict, first_seen: str, note: str) -> tuple[str, str]:
    tier = ev["tier"]
    uk = fmt_uk(o["uk"])
    title = (
        f"{TIER_LABEL.get(tier, '')}{COND_LABEL.get(o['condition'], '')}"
        f"{o['title'][:40]} {size_short(o['uk'], o['raw_size'])} 到手¥{ev['landed']} · {scfg['name']}"
    )
    lines = [
        f"### {TIER_LABEL.get(tier, '')}{COND_LABEL.get(o['condition'], '')}{o['title']}",
        f"- **尺码**：{size_line(o['uk'], o['raw_size'])}（店铺原文：{o['raw_size']}{'，换算按店铺码制推测' if scfg.get('size_verified') is False else ''}）",
        f"- **配色**：{o['color'] or '—'}",
        f"- **店铺**：{scfg['name']}（{scfg.get('region', '')}）",
        f"- **标价**：{money(o['price'], o['currency'])}，店铺运费估 {money(ev['shipping'], o['currency'])}",
        f"- **到手成本**：约 ¥{ev['landed']}{'' if ev['fx_live'] else '（汇率为兜底值）'}",
        f"- **预估利润**：约 ¥{ev['profit']}（按售价 1050、转运 ¥{ev['forwarder']:g}、国内邮费 10）",
        f"- **成色**：{ {'new': '全新', 'used': '二手，请人工看成色', 'unknown': '未知，请人工确认'}[o['condition']] }",
        f"- **检测**：首次 {first_seen}，确认 {ts()}（北京时间）",
    ]
    if note:
        lines.append(f"- **验证**：{note}")
    if o.get("note"):
        lines.append(f"- **备注**：{o['note']}")
    lines.append(f"- **链接**：{o['url']}")
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


def scan_store(scfg: dict, st: dict) -> StoreResult:
    known = sorted({v["product_id"] for k, v in st["variants"].items() if v["store"] == scfg["id"]})
    cfg2 = dict(scfg, _known_products=known)
    try:
        return PARSERS[scfg["type"]].scan(cfg2)
    except Exception as e:  # 解析器自身出错：整店未知
        return StoreResult(store=scfg["id"], ok=False, error=f"解析器异常：{e.__class__.__name__}: {e}")


def run(dry: bool = False, only: str | None = None, state_path: Path | None = None) -> int:
    cfg = load_cfg()
    state_path = state_path or ROOT / "state" / "state.json"
    st = load_state(state_path)
    st.setdefault("meta", {})
    now = ts()
    confirm_runs = int(cfg["rules"]["confirm_runs"])
    alerts: list[tuple[str, str]] = []
    health_msgs: list[tuple[str, str]] = []
    run_log = {"time": now, "stores": {}}

    for scfg in cfg["stores"]:
        if not scfg.get("enabled", True) or (only and scfg["id"] != only):
            continue
        sid = scfg["id"]
        ss = st["stores"].setdefault(sid, {"fail": 0, "alerted": False, "baseline": False})
        res = scan_store(scfg, st)
        mine = {k: v for k, v in st["variants"].items() if v["store"] == sid}

        if not res.ok:
            ss["fail"] += 1
            ss["last_error"] = res.error
            run_log["stores"][sid] = f"失败：{res.error}"
            for v in mine.values():  # 失败会打断连续确认
                v["streak"] = 0
            if ss["fail"] >= cfg["rules"]["fail_alert_after"] and not ss["alerted"]:
                ss["alerted"] = True
                health_msgs.append((f"【监控失效】{scfg['name']}", f"连续 {ss['fail']} 次抓取失败，这家店的尺码状态现在一律按“未知”处理，不会推有货。\n\n最近错误：{res.error}\n\n时间：{now}"))
            continue

        if ss.get("alerted"):
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

            if not ss["baseline"]:  # 第一次扫这家店：当前库存记为基线，不算“上新”
                v["notified_tier"] = ev["tier"]
                continue
            tier = ev["tier"]
            if tier not in PUSH_TIERS or TIER_RANK[tier] <= TIER_RANK.get(v.get("notified_tier"), 0):
                continue
            if v["streak"] < confirm_runs:
                continue  # 等下一轮复查
            note = ""
            if ss.get("anomaly"):
                note = "；".join(x for x in (note, "该店刚出现过大面积同时上新，请重点核实") if x)
            alerts.append(alert_text(d, ev, scfg, v["first_in"] or now, note))
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

    # —— 发送 ——
    if len(alerts) > cfg["rules"]["max_separate_alerts"]:
        body = "\n\n---\n\n".join(b for _, b in alerts)
        notify.send(f"【{len(alerts)} 条上新/降价】Hiangle 监控", body, dry=dry)
    else:
        for t, b in alerts:
            notify.send(t, b, dry=dry)
    for t, b in health_msgs:
        notify.send(t, b, dry=dry)

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
        "cond": {"new": "全新", "used": "二手", "unknown": "成色未知"}.get(v.get("condition"), "?"),
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
    now = ts()
    title = f"Hiangle 日报 {now[:10]}：{len(good)} 个达标 / {len(rows)} 个有货"

    # ---------- 纯文本 ----------
    t = [f"Hiangle 日报 {now}（北京时间）", f"当前有货 {len(rows)} 个尺码，达到推送门槛 {len(good)} 个。{'' if live else '（汇率为兜底值）'}", "", "【达到门槛】"]
    for v in good:
        r = _cost_row(v)
        t.append(f"- {r['tier']}{COND_LABEL.get(v['condition'], '')}{size_short(v['uk'], v['raw_size'])} 到手¥{r['landed']} 利润≈¥{r['profit']} · {stores.get(v['store'], {}).get('name', v['store'])} · {r['title'][:40]} · {r['url']}")
    if not good:
        t.append("- 暂无")
    by_store: dict = {}
    for v in rows:
        by_store.setdefault(v["store"], []).append(v)
    for sid, vs in by_store.items():
        t += ["", f"【{stores.get(sid, {}).get('name', sid)}】{len(vs)} 个有货"]
        for v in sorted(vs, key=lambda x: (x["title"], x["uk"] if x["uk"] is not None else 99)):
            r = _cost_row(v)
            t.append(f"- EU {r['eu']} / UK {r['uk']} / US男 {r['usm']}（原文 {r['raw']}） {r['price']} → 到手¥{r['landed']} 利润≈¥{r['profit']} {r['cond']} · {r['title'][:30]} {r['color'][:20]}")
    t += ["", "【运行情况】", f"- 今天已运行 {st['meta'].get('runs_today', 0)} 次，最近一次 {st['meta'].get('last_run', '-')}"]
    for sid, ss in st["stores"].items():
        state = f"失败 {ss['fail']} 次：{ss.get('last_error', '')}" if ss.get("fail", 0) else st["meta"].get("last_log", {}).get("stores", {}).get(sid, "正常")
        t.append(f"- {stores.get(sid, {}).get('name', sid)}：{state}")

    # ---------- HTML ----------
    css_td = "padding:4px 8px;border-bottom:1px solid #ddd;font-size:13px;white-space:nowrap"
    css_th = css_td + ";background:#f3f3f3;text-align:left"
    head = "".join(f"<th style='{css_th}'>{x}</th>" for x in ["欧码", "UK", "US男", "店铺原文", "标价", "到手成本", "预估利润", "成色", "款式 / 配色", "链接"])

    def tr(v, hl=False):
        r = _cost_row(v)
        bg = "background:#fff6d6;" if hl else ""
        cells = [f"<b>{_h.escape(r['eu'])}</b>", r["uk"], r["usm"], _h.escape(r["raw"]), _h.escape(r["price"]),
                 f"¥{r['landed']}", f"¥{r['profit']}", r["cond"],
                 _h.escape(f"{r['tier']} {r['title'][:38]} · {r['color'][:24]}"),
                 f"<a href='{_h.escape(r['url'])}'>打开</a>"]
        return "<tr>" + "".join(f"<td style='{bg}{css_td}'>{c}</td>" for c in cells) + "</tr>"

    hp = [f"<div style='font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222'>",
          f"<h2 style='margin:0 0 4px'>Hiangle 日报</h2><div style='color:#666;font-size:13px'>{now}（北京时间） · 当前有货 {len(rows)} 个尺码，达标 {len(good)} 个{'' if live else ' · 汇率为兜底值'}</div>",
          "<h3>达到门槛</h3>"]
    if good:
        hp.append(f"<table style='border-collapse:collapse'><tr>{head}<th style='{css_th}'>店铺</th></tr>")
        for v in good:
            hp.append(tr(v, True).replace("</tr>", f"<td style='{css_td}'>{_h.escape(stores.get(v['store'], {}).get('name', v['store']))}</td></tr>"))
        hp.append("</table>")
    else:
        hp.append("<p>暂无</p>")
    hp.append("<h3>各店全部有货尺码</h3>")
    for sid, vs in by_store.items():
        hp.append(f"<h4 style='margin:14px 0 4px'>{_h.escape(stores.get(sid, {}).get('name', sid))} · {len(vs)} 个有货</h4><table style='border-collapse:collapse'><tr>{head}</tr>")
        for v in sorted(vs, key=lambda x: (x["title"], x["uk"] if x["uk"] is not None else 99)):
            hp.append(tr(v, v.get("tier") in PUSH_TIERS))
        hp.append("</table>")
    hp.append("<h3>运行情况</h3><ul style='font-size:13px'>")
    hp.append(f"<li>今天已运行 {st['meta'].get('runs_today', 0)} 次，最近一次 {st['meta'].get('last_run', '-')}</li>")
    for sid, ss in st["stores"].items():
        state = f"失败 {ss['fail']} 次：{ss.get('last_error', '')}" if ss.get("fail", 0) else st["meta"].get("last_log", {}).get("stores", {}).get(sid, "正常")
        hp.append(f"<li>{_h.escape(stores.get(sid, {}).get('name', sid))}：{_h.escape(state)}</li>")
    hp.append("</ul><p style='color:#888;font-size:12px'>到手成本 = (标价 + 店铺运费估算) × 汇率 × 1.015；预估利润 = 1050 − 国内邮费 − 转运费 − 到手成本。黄色行 = 达到推送门槛。</p></div>")
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
        if dry or not sent:
            return  # 还没配置通知渠道（或演练）：不记为已发送，配好后会补发
        st["meta"]["last_digest"] = today
        st["meta"]["first_summary_sent"] = True


def check(store_id: str) -> int:
    """验收用：打印某家店本轮解析出的每个尺码，拿去和浏览器人工核对。"""
    cfg = load_cfg()
    scfg = next(s for s in cfg["stores"] if s["id"] == store_id)
    res = PARSERS[scfg["type"]].scan(dict(scfg, _known_products=[]))
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
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(dry=a.dry_run, only=a.only, state_path=Path(a.state) if a.state else None)
    if a.cmd == "check":
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
