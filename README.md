# Five Ten Hiangle 全球库存监控

> 接手开发请先读 [HANDOFF.md](HANDOFF.md)（2026-11-04 会话的全部改动、环境坑、待办）。

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
| 只记录 | 其他，或预估利润 < ¥150 | — | 只进日报 |

二手货标题加【二手】，近新的加【近新】，成色未知的加【成色未知】。预估利润 = 售价（全新 1050，二手和近新 800）− 国内邮费 10 − 转运费（美国 100，其他国家暂按 150）− 到手成本。

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
| GearX / Outdoor Gear Exchange | 美国 | Shopify 库存接口（新旧都卖） | **能读**：Hiangle 男款 2 个尺码有货 $160；女款全缺 |

### 2026-11-04 第二批：折扣 / 综合运动鞋 / 二手 / 日本

| 店铺 | 渠道类型 | 实测 |
| --- | --- | --- |
| Bergzeit（德国） | 户外店，季末常打折 | 能读：男款 €155.95，Pro €182.20，逐码 |
| SportsShoes（英国/德国站） | **综合跑鞋店**，攀岩鞋常被当普通鞋清仓 | 能读：英国站 £59.99（原价 £119.99）、德国站 €49.59（-66%），都缺货；页面不分尺码，有货即推，请自己看码 |
| Poshmark（美国） | 二手 / 闲置 | 能读：10+ 条 Hiangle，二手 $39 起 |
| Yahoo!购物（日本） | 综合电商（含 ZOZOTOWN、运动鞋店） | **要密钥**：developer.yahoo.co.jp 注册应用，Client ID 填到 GitHub Secrets 的 `YAHOO_JP_APPID` |
| 乐天市场（日本） | 综合电商 | **要密钥**：webservice.rakuten.co.jp 注册，填 `RAKUTEN_APP_ID`（新版接口还要 `RAKUTEN_ACCESS_KEY`）；乐天正在换接口地址，填好后需要实测 |

日本国内常规价约 19,800 日元（≈ ¥950），打 8–9 折或叠积分就可能进门槛。日本店一个页面包含多个尺码，接口不给逐码库存，所以统一按“码制不明”（¥850 线）判断。日本转运费暂按 ¥150 算。

读不了：Vinted（数据在浏览器端加载）、Kleinanzeigen（价格不在页面结构化数据里，暂缓）、Mercari 美国 / Sierra / Bike24（403）、CampSaver、Steep & Cheap、Last Hunt、Hardloop、Klimschoenen（比价站，无结构化数据）、乐天/Yahoo 网页版（被拦，只能走接口）。

试过但读不了、已删掉：Snowleader、Bike24（403 拦截）；Varuste.net、SportsShoes、Barrabes、Absolute-Snow（页面没有逐码数据）；Sportfits、Neptune（商品页 404）；Climbing Anchors、Snap Climbing、Wild Earth、Altitude Sports（不是 Shopify）。
能读但没卖 Hiangle：Rock+Run、Climb On Equipment、Bivouac。

这些店在 config.yaml 里标了 `trial: true`（试运行）：读不了**不发“监控失效”**，只在日报“运行情况”里显示原因；读到达标的货照常推，推送里注明“试运行，请核实”。
验收方法：Actions → hiangle-monitor → Run workflow，mode 选 `check`，store 填店铺 id（或 `all`），对照网页核对尺码和库存。通过就删掉 `trial: true`；一直失败就把整段删掉。

想试新店：mode 选 `probe`，targets 填域名（如 `sportfits.eu`，按 Shopify 试）或商品链接，日志里会写能不能读、有没有逐码数据。

### 2026-11-04 新增的规则

- **推送失败会重发**：微信和邮件都没发出去时，不算“已推送”，下一轮自动重发；渠道出错每天单独提醒一次，日报里也会显示。
- **首次扫描就已达标的货也推一次**：以前会被当成“基线”静默记录（Geartrade 那双 $38 女款 4.5 码就是这样一直没推过）。
- **降价提醒**：同一尺码价格连续两轮确认后比之前低 10% 以上，就推一条“降价”（还没到门槛也推，方便黑五/清仓时判断）。`price_drop_pct` 改幅度，`price_drop_push: false` 改成只进日报。
- **日报新增**：“离门槛最近”前 5 名（差多少钱）、“近 7 天明显降价”。
- Shopify 店有划线原价的，推送备注里写原价和折扣。

### 2026-11-05 合并 10-09 扩展版（新增 54 个来源，含 eBay 6 站，全部试运行；启用的来源合计 67 个）

10-09 做好的扩展版当时没上传，这次和 11-04 的版本合并。重复的来源（Bergzeit、GearX、Poshmark）保留 11-04 的写法，因为线上已经有它们的状态记录；eBay 换成新写的解析器，覆盖 6 个站点。

**新品店（每 15 分钟）**：16 个——Outnorth（瑞典）、Hardloop（法国）、Glisshop（法国）、Addnature（瑞典，奥特莱斯）、Sportano（波兰）、Intersport（德国）、XXL（挪威）、SportsShoes.com（英国）、Mountex（匈牙利）、Backcountry（美国）、Chamonix Outdoor（香港）、yocabito（日本）、Goofee 官网（日本）、Goofee Yahoo!ショッピング店（日本）、PUMP ONLINE STORE（日本）、グッぼる goodbouldering（日本）

**比价站（每小时）**：10 个——PriceRunner（英国）、PriceRunner（瑞典）、PriceRunner（丹麦）、billiger.de（德国比价）、beslist.nl（荷兰比价）、Achatmoinscher（法国比价）、Lyst（英国聚合）、BigGo（美国，含 Amazon/eBay/adidas US）、価格.com（日本比价）、에누리 Enuri（韩国比价）

**二手平台（每 1–4 小时）**：28 个——eBay 美国、eBay 英国、eBay 德国、eBay 法国、eBay 意大利、eBay 澳大利亚、Kleinanzeigen（德国二手）、willhaben（奥地利二手）、FINN.no（挪威二手）、Tori.fi（芬兰二手）、DBA.dk（丹麦二手）、Blocket（瑞典二手）、Bazoš.cz（捷克二手）、Bazoš.sk（斯洛伐克二手）、Bazoš.pl（波兰二手）、Marktplaats（荷兰二手）、2dehands（比利时二手）、Gumtree（英国二手）、Allegro Lokalnie（波兰二手）、Kijiji（加拿大二手）、SidelineSwap（美国二手）、Yahoo!オークション（日本拍卖）、ラクマ Rakuma（日本フリマ）、ジモティー Jimoty（日本本地二手）、당근마켓 Daangn（韩国本地二手）、번개장터 Bunjang（韩国二手）、Novelship（新加坡球鞋转售）、露天拍賣 Ruten（台湾）

- 设置放在 `config.d/*.yaml`，和 `config.yaml` 的 stores 合并读取。新来源的写法规范见 `PARSER_SPEC.md`。
- **新规则（2026-11-05 你定的）**：预估利润低于 ¥150 的不推送，只进日报（`rules.min_profit`）。二手和近新的利润按售价 ¥800 算（`profit.used_sale_price`）；二手平台上成色不明的也按 ¥800 算。
- **按成色推送**：只推全新、近新和成色未知的；有使用痕迹的二手只进日报（`rules.push_conditions`）。
- 比价站里认不出尺码的条目只进日报，不推送，因为这类条目太多。
- 比价站和二手平台用 `every_minutes` 降低检查频率，减少被封的风险；一条 listing 出现一次就算数（`confirm_runs: 1`）。
- 日报不再逐码列出全部有货尺码，因为几百行会超过 Gmail 的 102KB 上限被截断；改成每个来源一行概况。
- 折扣站（Dealabs、mydealz 等 7 个）的代码已经写好，但目前停用，在 `config.d/deals.yaml` 里设了 `enabled: false`。
- 读不了、已排除：Zalando、各地 adidas 官网、Vinted、Leboncoin、idealo、Deporvillage、OzBargain（有反爬拦截，按规则不绕过）；MTBiker、Subito、Amazon 网站本身（你确认排除）；中国大陆渠道全部不做。

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
