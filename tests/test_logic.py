"""状态机测试：用假店铺模拟各种情况，确认只在该推的时候推。

运行：python -m pytest -q tests/  （或 python tests/test_logic.py）
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hmon import money, notify, run as R  # noqa: E402
from hmon.core import IN, OUT, UNKNOWN, Obs, StoreResult  # noqa: E402

SENT = []


class Fake:
    """可编程的假店铺。"""

    plan = []  # 每轮返回什么

    @classmethod
    def scan(cls, cfg):
        step = cls.plan.pop(0)
        if step == "fail":
            return StoreResult(store="fake", ok=False, error="HTTP 403")
        res = StoreResult(store="fake", ok=True)
        for pid, size, status, price in step:
            res.products_checked.add(pid)
            res.obs.append(Obs("fake", pid, "Hiangle 测试", "https://x", f"{pid}-{size}", str(size), size,
                               "", price, "CNY", status))
        return res


CFG = {
    "profit": {"sale_price": 1050, "domestic_post": 10, "fx_fee": 0.0, "forwarder": {"default": 100}},
    "thresholds": {"core_uk": [4, 9], "strong": 750, "normal": 850, "cold": 650},
    "rules": {"confirm_runs": 2, "fail_alert_after": 3, "max_separate_alerts": 5, "digest_hour_bj": 99},
    "stores": [{"id": "fake", "name": "假店", "type": "fake", "currency": "CNY", "region": "X", "shipping": 0}],
}


def setup():
    SENT.clear()
    R.PARSERS["fake"] = Fake
    R.load_cfg = lambda: CFG
    money._cache.update(r={"CNY": 1.0}, live=True)
    notify.send = lambda t, b, **k: SENT.append(t)
    R.notify.send = notify.send
    return Path(tempfile.mkdtemp()) / "s.json"


def go(path, step):
    Fake.plan.append(step)
    SENT.clear()
    R.run(state_path=path)
    return [t for t in SENT if "日报" not in t]


def test_restock_needs_two_runs():
    p = setup()
    assert go(p, [("a", 8, OUT, 700)]) == []           # 基线
    assert go(p, [("a", 8, IN, 700)]) == []            # 第一次看到有货：不推
    out = go(p, [("a", 8, IN, 700)])                   # 第二次确认：推
    assert len(out) == 1 and "好价" in out[0]
    assert go(p, [("a", 8, IN, 700)]) == []            # 不重复推


def test_baseline_is_silent():
    p = setup()
    assert go(p, [("a", 8, IN, 600)]) == []
    assert go(p, [("a", 8, IN, 600)]) == []


def test_unknown_breaks_confirmation():
    p = setup()
    go(p, [("a", 8, OUT, 700)])
    assert go(p, [("a", 8, IN, 700)]) == []
    assert go(p, [("a", 8, UNKNOWN, 700)]) == []
    assert go(p, [("a", 8, IN, 700)]) == []            # 重新计数
    assert len(go(p, [("a", 8, IN, 700)])) == 1


def test_flicker_is_not_pushed():
    p = setup()
    go(p, [("a", 8, OUT, 700)])
    assert go(p, [("a", 8, IN, 700)]) == []
    assert go(p, [("a", 8, OUT, 700)]) == []           # 闪现后消失：不推


def test_store_failure_alert_once_and_recovery():
    p = setup()
    go(p, [("a", 8, OUT, 700)])
    assert go(p, "fail") == []
    assert go(p, "fail") == []
    out = go(p, "fail")
    assert len(out) == 1 and "监控失效" in out[0]
    assert go(p, "fail") == []                          # 不重复报
    out = go(p, [("a", 8, OUT, 700)])
    assert len(out) == 1 and "恢复" in out[0]


def test_failure_between_confirmations_blocks_push():
    p = setup()
    go(p, [("a", 8, OUT, 700)])
    go(p, [("a", 8, IN, 700)])
    go(p, "fail")
    assert go(p, [("a", 8, IN, 700)]) == []
    assert len(go(p, [("a", 8, IN, 700)])) == 1


def test_price_drop_across_tier():
    p = setup()
    go(p, [("a", 8, IN, 900)])                          # 基线：只记录档
    assert go(p, [("a", 8, IN, 800)]) == []             # 降到普通档，第一次
    out = go(p, [("a", 8, IN, 800)])
    assert len(out) == 1 and "好价" not in out[0]
    assert go(p, [("a", 8, IN, 700)]) == []             # 再降到好价，第一次
    out = go(p, [("a", 8, IN, 700)])
    assert len(out) == 1 and "好价" in out[0]


def test_price_rises_between_checks_no_push():
    p = setup()
    go(p, [("a", 8, OUT, 700)])
    go(p, [("a", 8, IN, 700)])
    out = go(p, [("a", 8, IN, 900)])                    # 复查时涨价到门槛外
    assert out == []


def test_cold_size_threshold():
    p = setup()
    go(p, [("a", 3, OUT, 700), ("b", 3, OUT, 600)])
    go(p, [("a", 3, IN, 700), ("b", 3, IN, 600)])
    out = go(p, [("a", 3, IN, 700), ("b", 3, IN, 600)])
    assert len(out) == 1 and "冷门码" in out[0]


def test_mass_flip_is_rejected():
    p = setup()
    go(p, [(f"p{i}", 8, OUT, 700) for i in range(10)])
    out = go(p, [(f"p{i}", 8, IN, 700) for i in range(10)])
    assert len(out) == 1 and "异常" in out[0]
    out = go(p, [(f"p{i}", 8, IN, 700) for i in range(10)])
    assert out == []                                    # 下一轮仍一致：接受，但还要再确认一轮
    out = go(p, [(f"p{i}", 8, IN, 700) for i in range(10)])
    assert len(out) == 1 and "10 条" in out[0]          # 合并成一条推送


def test_restock_after_sellout_pushes_again():
    p = setup()
    go(p, [("a", 8, OUT, 700)])
    go(p, [("a", 8, IN, 700)])
    assert len(go(p, [("a", 8, IN, 700)])) == 1
    go(p, [("a", 8, OUT, 700)])
    go(p, [("a", 8, IN, 700)])
    assert len(go(p, [("a", 8, IN, 700)])) == 1


def test_missing_variant_marked_out():
    p = setup()
    go(p, [("a", 8, IN, 700), ("a", 9, OUT, 700)])
    go(p, [("a", 9, OUT, 700)])                         # 8 码从列表消失 = 缺货
    go(p, [("a", 8, IN, 700), ("a", 9, OUT, 700)])
    assert len(go(p, [("a", 8, IN, 700), ("a", 9, OUT, 700)])) == 1


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("通过", name)
            except AssertionError as e:
                fails += 1
                print("失败", name, e)
    print("失败数", fails)
    sys.exit(1 if fails else 0)
