"""2026-11-05 合并扩展版后新增的规则：最低利润线、二手售价、按成色推送、低频来源、比价站码制不明不推、config.d 合并。"""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hmon import money, notify, run as R  # noqa: E402
from hmon.core import IN, Obs, StoreResult  # noqa: E402

ORIG_LOAD = R.load_cfg  # 其他测试会替换 R.load_cfg，先存一份真的
SENT = []

BASE = {
    "profit": {"sale_price": 1050, "used_sale_price": 800, "domestic_post": 10, "fx_fee": 0.0, "forwarder": {"default": 100}},
    "thresholds": {"core_uk": [4, 9], "strong": 750, "normal": 850, "cold": 650},
    "rules": {"confirm_runs": 2, "fail_alert_after": 3, "max_separate_alerts": 5, "digest_hour_bj": 99,
              "price_drop_pct": 10, "price_drop_push": True, "min_profit": 150,
              "push_conditions": ["new", "like_new", "unknown"]},
    "stores": [{"id": "fk", "name": "假店", "type": "fk", "currency": "CNY", "region": "X", "shipping": 0}],
}


class FK:
    plan = []
    calls = 0

    @classmethod
    def scan(cls, cfg):
        cls.calls += 1
        res = StoreResult(store="fk", ok=True)
        for pid, uk, price, cond in cls.plan[0]:
            res.products_checked.add(pid)
            res.obs.append(Obs("fk", pid, "Hiangle 测试", "https://x", "1", str(uk), uk, "", price, "CNY", IN, condition=cond))
        return res


def _obs(uk, price, cond="new"):
    return Obs("fk", "p", "Hiangle", "u", "1", str(uk), uk, "", price, "CNY", IN, condition=cond)


def setup(store_extra=None, plan=None):
    cfg = copy.deepcopy(BASE)
    cfg["stores"][0].update(store_extra or {})
    R.PARSERS["fk"] = FK
    R.load_cfg = lambda: cfg
    money._cache.update(r={"CNY": 1.0}, live=True)

    def send(t, b, **k):
        SENT.append(t)
        return ["测试 成功"]
    notify.send = send
    R.notify.send = send
    FK.plan, FK.calls = [plan or []], 0
    SENT.clear()
    return cfg, Path(tempfile.mkdtemp()) / "s.json"


def rounds(path, n):
    for _ in range(n):
        R.run(state_path=path)
    return [t for t in SENT if "日报" not in t]


def test_min_profit_demotes_thin_deals():
    cfg, _ = setup()
    assert money.evaluate(_obs(8, 800), {"region": "X"}, cfg)["tier"] == "record"   # 利润 140 < 150
    assert money.evaluate(_obs(8, 780), {"region": "X"}, cfg)["tier"] == "normal"   # 利润 160


def test_used_sale_price():
    cfg, _ = setup()
    ev = money.evaluate(_obs(8, 500, "like_new"), {"region": "X"}, cfg)
    assert ev["profit"] == 800 - 10 - 100 - 500 and ev["sale"] == 800
    ev = money.evaluate(_obs(8, 600, "like_new"), {"region": "X"}, cfg)
    assert ev["tier"] == "record"                                                    # 二手利润 90：不推
    ev = money.evaluate(_obs(8, 500, "unknown"), {"region": "X", "segment": "used"}, cfg)
    assert ev["sale"] == 800                                                         # 二手平台成色不明按二手算
    assert money.evaluate(_obs(8, 500, "unknown"), {"region": "X"}, cfg)["sale"] == 1050


def test_used_condition_not_pushed_but_like_new_is():
    _, p = setup({"segment": "used", "confirm_runs": 1}, [("a", 8, 400, "used"), ("b", 8, 400, "like_new")])
    out = rounds(p, 3)
    assert len(out) == 1 and "近新" in out[0]


def test_every_minutes_skips_scans():
    _, p = setup({"every_minutes": 120}, [("a", 8, 1000, "new")])
    rounds(p, 3)
    assert FK.calls == 1


def test_aggregator_unknown_size_not_pushed():
    _, p = setup({"segment": "aggregator", "confirm_runs": 1}, [("a", None, 500, "new"), ("b", 8, 500, "new")])
    out = rounds(p, 3)
    assert len(out) == 1 and "码制不明" not in out[0]


def test_real_config_loads_without_duplicates():
    cfg = ORIG_LOAD()
    ids = [s["id"] for s in cfg["stores"]]
    assert len(ids) == len(set(ids)) and len(ids) > 50
    for s in cfg["stores"]:
        if s.get("enabled", True):
            R.parser_for(s["type"])  # 每个启用的来源都有解析器
