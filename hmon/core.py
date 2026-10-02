from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

IN, OUT, UNKNOWN = "in", "out", "unknown"


class FetchError(Exception):
    """抓取失败或被拦截。整个店铺本轮记为“未知”，绝不当成有货。"""


_BLOCK_PAT = re.compile(
    r"cf-chl|challenge-platform|Just a moment\.\.\.|captcha|Access Denied|"
    r"Request unsuccessful|Pardon Our Interruption|are you a robot",
    re.I,
)


def fetch(url: str, *, expect_json: bool = False, timeout: int = 25, retries: int = 2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"},
                timeout=timeout,
            )
            if r.status_code in (403, 429, 503):
                raise FetchError(f"HTTP {r.status_code}（可能被反爬拦截）")
            if r.status_code == 404:
                raise FetchError("HTTP 404（页面不存在）")
            if r.status_code != 200:
                raise FetchError(f"HTTP {r.status_code}")
            if expect_json:
                try:
                    return r.json()
                except ValueError:
                    raise FetchError("返回的不是 JSON（可能是拦截页）")
            text = r.text
            if len(text) < 20000 and _BLOCK_PAT.search(text):
                raise FetchError("返回了人机验证/拦截页")
            return text
        except (requests.RequestException, FetchError) as e:
            last = e
            if isinstance(e, FetchError) and "404" in str(e):
                break
            time.sleep(2 + attempt * 3)
    raise FetchError(str(last))


@dataclass
class Obs:
    """一次检测中，某个商品某个尺码的状态。"""

    store: str
    product_id: str
    title: str
    url: str
    variant_id: str
    raw_size: str
    uk: float | None
    color: str
    price: float | None
    currency: str
    status: str  # in / out / unknown
    condition: str = "new"  # new / used / unknown
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.store}|{self.product_id}|{self.variant_id}"

    def to_dict(self):
        return asdict(self)


@dataclass
class StoreResult:
    store: str
    ok: bool
    obs: list[Obs] = field(default_factory=list)
    error: str = ""
    # 本轮确实检查过的商品（用于判断“商品下架=缺货”）
    products_checked: set[str] = field(default_factory=set)
    # 确认已下架（404）的商品：其全部尺码记为缺货
    gone_products: set[str] = field(default_factory=set)
