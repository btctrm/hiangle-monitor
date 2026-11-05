# 写一个新来源解析器（给开发代理看的规范）

项目：/home/claude/hiangle（Python 3.11，依赖只有 requests、PyYAML、标准库）。监控 Five Ten Hiangle 全系（Hiangle / Hiangle Pro / 女款，所有配色）在全球网店、比价站、二手平台的逐码库存与价格。运行在 GitHub Actions（ubuntu，无浏览器，**不能用 Playwright**）。

## 你要交付的
1. `hmon/parsers/<module>.py`：实现 `scan(cfg: dict) -> StoreResult`。一个模块可服务多个 store 配置（例如 PriceRunner 的 uk/se/dk 用同一模块，靠 cfg 区分）。
2. `config.d/<group>.yaml`：形如
   ```yaml
   stores:
     - id: bergzeit            # 全局唯一，小写下划线
       name: Bergzeit（德国）
       type: bergzeit          # = 模块名
       segment: retail         # retail / aggregator / used / deals
       currency: EUR           # 页面没写币种时的默认值
       region: DE              # 决定转运费：US=100，其他默认 150
       shipping: 0             # 店铺寄到转运仓的运费估算（同币种）
       every_minutes: 0        # 0=每轮都查（约 15 分钟）；比价站 60；二手 120；折扣站 60
       confirm_runs: 2         # 新品零售 2；二手/折扣/比价站 1（一条 listing 出现即真实）
       size_verified: true     # 尺码换算是否确定
       # …你的模块需要的其他字段（urls、domain、search 等）
   ```
3. 用 `cd /home/claude/hiangle && python3 -m hmon check <id>` 实测通过（打印逐码结果），对照你抓到的原始数据核对至少 3 条。

## 可用的公共代码
```python
from ..core import IN, OUT, UNKNOWN, FetchError, Obs, StoreResult, fetch, UA
# fetch(url, expect_json=False) -> str | dict；403/429/503、人机验证页、非 JSON 会抛 FetchError（重试 2 次）
from ..sizes import to_uk, gender_from_title
# to_uk(raw, system, gender) -> UK 码 float 或 None；system: AUTO / UK / EU / US_M / US_W / US
#   AUTO 能识别 "UK 8" "8 (UK)" "EU 42 2/3" "US M 9" "Mens 11/Womens 12" "26.5cm" "265mm"
#   认不出返回 None（推送里会标“码制不明”，这是允许的，绝不要猜）
```
`Obs(store, product_id, title, url, variant_id, raw_size, uk, color, price, currency, status, condition="new", note="")`
- `product_id`：同一商品稳定不变（商品 handle / listing id / 规范化 URL 片段）。`variant_id`：同一商品内稳定（尺码 SKU；单件二手用 "1"）。key = store|product_id|variant_id，**必须跨运行稳定**，否则会被当成“新上架”误推。
- `status`：IN / OUT / UNKNOWN。**不确定一律 UNKNOWN**。
- `condition`：`new` / `like_new` / `used` / `unknown`。二手平台必须按平台字段或标题关键词判断（未使用/新品/NWT/neu/OVP/ungetragen/Neuf/새상품/미사용 → new；ほぼ未使用/未使用に近い/like new/wie neu/Très bon état/1 回のみ → like_new；有使用痕迹/used/gebraucht/中古/Bon état/worn → used；不明 → unknown）。
- `price` 用页面实际售价（数字），`currency` 用页面币种。
- 返回 `StoreResult(store=cfg["id"], ok=True, obs=[...], products_checked={...})`。`products_checked` 放本轮确实检查过的 product_id（程序据此把消失的尺码记为缺货）。二手/比价/折扣站：本轮搜索结果里**没出现**的旧 listing 视为下架——把本轮所有 listing 的 product_id 放进 products_checked，并把 `cfg.get("_known_products", [])` 里本轮没出现的放进 `res.gone_products`（仅当本轮搜索成功时）。
- 抓取失败、被拦、页面结构不对（找不到预期字段）→ 返回 `StoreResult(store=..., ok=False, error="原因")`，**整店本轮作废**，绝不返回半截数据冒充正常。
- 只收 Hiangle：标题/名称需包含 hiangle（大小写不敏感，也接受 "hi angle"、"hi-angle"、日文 ハイアングル、韩文 하이앵글）。过滤掉配件、其他鞋款。

## 硬规则
- 只用合法方式：普通 GET（桌面 UA）、站点自己公开的 JSON/JSON-LD/内嵌数据、RSS、sitemap、官方/公开 API。
- **禁止**：绕过/破解验证码或 Cloudflare/DataDome/Akamai 挑战、伪装指纹、换 IP、登录、注册、加购物车、提交表单、Playwright。
- 每次 scan 请求数尽量少（每店 ≤ 6 次）；不要遍历 sitemap 的大量 URL。
- 不改动 hmon/core.py、hmon/run.py、hmon/sizes.py、config.yaml、其他组的文件。需要公共能力就在自己模块里写私有函数。
- 中国大陆渠道不做。
