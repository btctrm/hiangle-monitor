# Five Ten Hiangle 全球库存监控

每 15 分钟检查一次各家网店里 Hiangle（男款、女款、Pro、全部配色）每个尺码的库存和价格。
**真有货而且买入有利润**时，推送到微信和邮件；每天早上 9 点（北京时间）再发一封日报邮件。

## 它怎么避免“一直说有货”

1. **读库存数据，不搜网页文字**：缺货的尺码在网页上通常也显示，只是灰掉，搜文字永远能搜到。
2. **被拦截就记“未知”**：遇到人机验证、403、页面改版、字段缺失，这家店整轮作废，绝不当有货。连续 3 次失败发一条“监控失效”。
3. **两次确认**：同一尺码要连续两轮（约 15–30 分钟）都有货、价格都达标，才推。闪一下就消失的不推。
4. **双来源核对**（Bergfreunde 系）：页面结构化数据说有货、下单按钮数据也说能买，两个都对上才算。
5. **不跟踪库存的商品不信**（Shopify 店）：店家没开库存跟踪的商品，接口永远显示有货，一律记“未知”。
6. **大面积同时变有货**：一轮里 80% 以上尺码突然都有货，多半是页面出错，先作废并提醒你。
7. **同一件货不重复推**：只在缺货→有货、新上架、降价跨档时推。

> 实测发现：SpokeX、Délire 这类 Shopify 店，缺货尺码也能加进购物车（到结账才拦），所以“能加购物车”不能当有货证据，本程序没用它。

## 推送规则（config.yaml 里能改）

到手成本 = (标价 + 店铺寄到转运仓的运费) × 当日汇率 × 1.015

| 档位 | 尺码 | 到手成本 | 推送 |
| --- | --- | --- | --- |
| 【好价】 | UK 4–9 | ≤ ¥750 | 微信 + 邮件 |
| 普通 | UK 4–9 | ≤ ¥850 | 微信 + 邮件 |
| 【冷门码】 | UK 4 以下 / 9 以上 | ≤ ¥650 | 微信 + 邮件 |
| 【码制不明】 | 店铺尺码写法认不出 | ≤ ¥850 | 微信 + 邮件，请你自己看码 |
| 只记录 | 其他 | — | 只进日报 |

二手货标题加【二手】，成色未知的加【成色未知】。预估利润 = 1050 − 国内邮费 10 − 转运费（美国 100，其他国家暂按 150）− 到手成本。

尺码统一换成 UK 码（Five Ten 男女款 UK 码通用）：US 男 = UK + 0.5，US 女 = UK + 1.5，EU 按官方表（42 = UK 8，43⅓ = UK 9）。认不出的写法（比如卖家自填“41.5”）不猜，标“码制不明”，推送里附店铺原文。

## 现在监控的店（2026-09-30 实测可读）

| 店铺 | 地区 | 怎么读 | 验收 |
| --- | --- | --- | --- |
| Bergfreunde | 德国 | 双来源核对 | 已对照实际页面：22 个尺码全部一致 |
| Alpinetrek（Bergfreunde 英国站） | 英国 | 双来源核对 | 同平台，数据一致 |
| SpokeX | 美国 | Shopify 库存接口 | 尺码按美码男款推测，**待你人工验收** |
| Délire Escalade | 加拿大 | Shopify 库存接口 | 尺码按美码男款推测，**待验收**；页面清仓价拿不到，到手成本偏高 |
| Geartrade | 美国（寄卖/二手） | Shopify 库存接口 | 尺码多为卖家自填，常标“码制不明” |
| Trekkinn | 西班牙 | 页面结构化数据 | 抽查 1 个尺码一致；价格每次刷新会差 $2 左右 |
| eBay 美国 | 美国 | 官方接口 | 需要你注册开发者账号填密钥，未实测 |

读不了的（会被拦截）：BananaFingers、Adidas 官网、Backcountry、Bike24、Oliunid、SportScheck、ZOZO。免费方案先不接。

### 2026-11-04 新增（试运行）

| 店铺 | 地区 | 怎么读 | 2026-11-04 在 GitHub 上实测 |
| --- | --- | --- | --- |
| eBay 英国、eBay 德国 | 英 / 德 | 官方接口，和 eBay 美国共用一套密钥 | 没密钥，跳过；德国站有不少 Hiangle Pro 新鞋/二手 |
| EpicTV Shop | 英国 | 页面结构化数据（欧码） | **能读**：Hiangle Pro 13 个尺码有货 $146.87（到手约 ¥1030）；女款全缺 |
| Sportfits | 欧洲 | Shopify 商品页（站内搜索接口 404，直接读写死的商品页） | 待复测 |
| Neptune Mountaineering | 美国 | Shopify 商品页（站内搜索搜不到，直接读商品页） | 待复测 |

试过但读不了、已删掉：Snowleader（403 拦截）、Varuste.net、SportsShoes、Barrabes（页面没有逐码数据）。

这些店在 config.yaml 里标了 `trial: true`（试运行）：读不了**不发“监控失效”**，只在日报“运行情况”里显示原因；读到达标的货照常推，推送里注明“试运行，请核实”。
验收方法：Actions → hiangle-monitor → Run workflow，mode 选 `check`，store 填店铺 id（或 `all`），对照网页核对尺码和库存。通过就删掉 `trial: true`；一直失败就把整段删掉。

想试新店：mode 选 `probe`，targets 填域名（如 `sportfits.eu`，按 Shopify 试）或商品链接，日志里会写能不能读、有没有逐码数据。

### 2026-11-04 新增的规则

- **推送失败会重发**：微信和邮件都没发出去时，不算“已推送”，下一轮自动重发；渠道出错每天单独提醒一次，日报里也会显示。
- **首次扫描就已达标的货也推一次**：以前会被当成“基线”静默记录（Geartrade 那双 $38 女款 4.5 码就是这样一直没推过）。
- **降价提醒**：同一尺码价格连续两轮确认后比之前低 10% 以上，就推一条“降价”（还没到门槛也推，方便黑五/清仓时判断）。`price_drop_pct` 改幅度，`price_drop_push: false` 改成只进日报。
- **日报新增**：“离门槛最近”前 5 名（差多少钱）、“近 7 天明显降价”。
- Shopify 店有划线原价的，推送备注里写原价和折扣。

---

## 部署（约 20 分钟，全部免费）

### 第 1 步：建 GitHub 仓库

1. 注册/登录 https://github.com ，右上角 **+ → New repository**。
2. 名字随便（如 `hiangle-monitor`），选 **Public**。
   - 为什么选公开：公开仓库的 GitHub Actions 分钟数不限；私有仓库每月只有 2000 分钟，每 15 分钟跑一次一个月要约 2900 分钟，会超。仓库里没有任何密码（密码放在第 3 步的 Secrets 里，别人看不到）。
   - 想用私有仓库：把 `.github/workflows/monitor.yml` 里的 `*/15` 改成 `*/30`（每月约 1440 分钟）。
3. 建好后点 **uploading an existing file**，把解压后的全部文件拖进去，点 **Commit changes**。
   - Mac 上 `.github` 是隐藏文件夹，拖不上去的话：在仓库页面点 **Add file → Create new file**，文件名填 `.github/workflows/monitor.yml`，把压缩包里这个文件的内容粘贴进去，保存。

### 第 2 步：拿通知密钥

- **微信（PushPlus）**：打开 https://www.pushplus.plus ，微信扫码登录，在“一对一推送”里复制你的 **token**。
- **邮件（Gmail）**：Google 账号先开“两步验证”，再到 https://myaccount.google.com/apppasswords 生成一个 **应用专用密码**（16 位）。
- 也可以用 Server酱（https://sct.ftqq.com ）代替 PushPlus，拿 SendKey。

### 第 3 步：把密钥填进 GitHub

仓库页面 **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| 名字 | 填什么 |
| --- | --- |
| `PUSHPLUS_TOKEN` | PushPlus 的 token |
| `SMTP_USER` | 你的 Gmail 地址 |
| `SMTP_PASS` | Gmail 应用专用密码 |
| `MAIL_TO` | 收通知的邮箱（可以就是同一个 Gmail） |
| `SERVERCHAN_KEY` | （可选）Server酱 SendKey |
| `EBAY_APP_ID` / `EBAY_CERT_ID` | （可选）eBay 开发者密钥 |

再到 **Settings → Actions → General → Workflow permissions**，选 **Read and write permissions**，保存（程序要把状态存回仓库）。

### 第 4 步：试跑

1. 仓库顶部 **Actions** 标签，如果提示启用就点启用。
2. 左边选 **hiangle-monitor → Run workflow**，mode 选 **test-notify** → 微信和邮箱应该各收到一条测试消息。
3. 再 **Run workflow**，mode 选 **run** → 第一次运行会发一封【首次运行】汇总（当前所有有货尺码），之后就每 15 分钟自动跑。

第一次运行把当前库存当“基线”，不会逐条推送；之后出现的补货、新上架、降价才推。

---

## 日常怎么用

- **收到推送**：点链接进去确认尺码和价格再下单。推送里有店铺原始尺码写法，以店铺为准。
- **日报**：每天 9 点后一封邮件，列出所有有货尺码、达标的、各店运行状态。哪天没收到，说明系统没在跑。
- **改门槛/运费/转运费**：在 GitHub 网页上直接编辑 `config.yaml`，保存即生效。
- **加一家 Shopify 店**：复制 `spokex` 那一段，改 `id`、`name`、`domain`、`currency`、`region`。
- **监控别的鞋**：把 `search`（搜索词）、`title_must`（标题必须包含的词）、`slug_must` 改成新鞋名；多款鞋可以复制店铺配置、换不同的 id。

## 验收待办（需要你用自己的浏览器看一眼）

SpokeX 和 Délire 的尺码只写数字，程序按美码男款换算。请打开它们的商品页看尺码表是不是 US 男码；如果是女码或 UK 码，把 `config.yaml` 里对应的 `size_system` 改成 `US_W` 或 `UK`，并把 `size_verified` 改成 `true`。

## 本地运行（可选）

```
pip install -r requirements.txt
python -m hmon check bergfreunde_eu   # 打印某家店每个尺码的解析结果，用来和网页核对
python -m hmon run --dry-run          # 跑一轮，只打印不发送
python tests/test_logic.py            # 状态机测试（补货、闪现、失效、降价等 12 种情况）
```
