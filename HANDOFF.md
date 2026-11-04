# 交接报告：Hiangle 库存监控，2026-11-04 会话的全部新增内容

> 读者：接手这个仓库的下一个 AI 或开发者。
> 范围：从本会话接手时的提交 `a6a677c`（state 2026-11-04T18:15:43Z）起，到 PR #3 合并后为止的**所有新增和改动**。在此之前的代码由另一个 AI 写，本报告只在必要时简单交代。
> 时间：2026-11-04（UTC）/ 2026-11-05 凌晨（北京时间）。文中时间未注明的都是北京时间。
> 写法约定：**【未确认】** = 没能实际验证的内容，后面写明查过哪里。

---

## 0. 一段话说清现状

- 仓库 `btctrm/hiangle-monitor` 是一个跑在 GitHub Actions 上、每 15 分钟一轮的 Five Ten Hiangle 攀岩鞋全球库存/价格监控，用于“海外低价买入 → 国内 ¥1050 卖出”。达标就发邮件，每天 9 点发日报。
- 本会话合并了 3 个 PR：
  - [btctrm/hiangle-monitor#1](https://github.com/btctrm/hiangle-monitor/pull/1)：可靠性和推送逻辑改进，新增 GearX、EpicTV、eBay 英/德站。squash 后提交 `5cd4372`。
  - [btctrm/hiangle-monitor#2](https://github.com/btctrm/hiangle-monitor/pull/2)：扩大渠道，新增 Bergzeit、SportsShoes 清仓、Poshmark 二手、日本 Yahoo!购物和乐天。squash 后提交 `0610de0`。
  - [btctrm/hiangle-monitor#3](https://github.com/btctrm/hiangle-monitor/pull/3)：推送邮件改 HTML、寄卖店读取成色、码制不明附推测。squash 后提交 `67ab28e`。
- 线上 `main` 正在用这些代码跑。最近一次快照（03:30）：16 家店铺/渠道里，11 家读取正常，5 家因为没有密钥被跳过（eBay 3 个站、Yahoo、乐天）。
- **门槛没有改动**，这是用户的明确要求。
- **待用户回答**：最低利润线定多少、二手售价按多少算（见第 10 节）。

---

## 1. 背景：接手时系统是什么样子（之前那个 AI 做的）

接手时的代码见 `README.md` 原文。要点：

- 入口 `python -m hmon run`，主流程在 `hmon/run.py`，状态存在 `state/state.json`（每轮由 Actions 机器人提交回仓库）。
- 解析器：`bergfreunde`（JSON-LD 和下单按钮双来源核对）、`shopify`（`/products/<handle>.js`，只认 `inventory_management == "shopify"`）、`jsonld`（ProductGroup/hasVariant）、`ebay`（官方 Browse API，**一直没有密钥，从未实测**）。
- 档位按**到手成本** `(标价 + 店铺运费) × 汇率 × 1.015` 判断：
  - 主力码 UK 4–9：≤ ¥750 为“好价”，≤ ¥850 为“普通”；
  - 非主力码：≤ ¥650 为“冷门码”；
  - 码制不明：≤ ¥850。
  - 档位不看利润。
- 推送规则：连续两轮确认，只在“缺货 → 有货、新上架、降价跨档”时推。首次扫描一家店时，当时的库存记为基线，不推送。
- 原来的部署方式：用户把 zip 上传到仓库，`unpack.yml` 自动解压。注意这个流程会**删掉 zip 里的 `.github`**，所以改 workflow 不能靠上传 zip。

用户反馈的问题是“一两个月只推送过 1 次，达标的一直只有一个，是不是坏了”。诊断结论：

1. 抓取没有坏。
2. 全新货的到手成本普遍在 ¥984–1400，比门槛高 25–35%，所以几乎不会触发。
3. 唯一达标的那一条（Geartrade $38.35）在首次扫描时被当成基线，永远不会推送。
4. 通知发送失败时，旧代码仍然把它记为“已推送”，导致提醒静默丢失。

---

## 2. 用户偏好和已经做出的决定（重要）

**通用偏好（来自用户设置）：**
- 用中文沟通。
- 生成的文件除了在对话里交付，还要写一份到 `/Users/yangwenda/Downloads/claude留档/<对话标题>/`。**云端会话写不到用户的 Mac**，每次都要在回复开头说明，并提醒用户补存。
- 多个任务时，在 `TASKS.md` 里建清单，完成一项打勾一项，新发现的事项也加进去。
- 无法确认的内容要标出来，并说明查过哪里。

**本会话里用户明确做出的决定：**

| 决定 | 原话或含义 |
| --- | --- |
| **门槛保持不变，宁高勿低** | “门槛还是要高一点，因为周期比较长，利润差加上海淘运费 100 元，还有丢件风险，不值当。” |
| **扩大搜索范围，重点是特殊渠道** | 打折渠道，以及把攀岩鞋当普通运动鞋卖的综合鞋店。用户记得以前有过这种打折。 |
| **不考虑微信推送** | 只用邮件。`PUSHPLUS_TOKEN` 和 `SERVERCHAN_KEY` 都是空的，也不用去配。 |
| 合并到 main | 用户说“先开始做吧，合并”，所以 PR #1、#2、#3 都由 AI 创建并 squash 合并。 |
| Geartrade $38.35 女款 4.5 码 | 用户看过实物页面：**是二手，但磨损非常少**。店铺数据里没有写成色。 |

---

## 3. 环境和操作须知（踩过的坑）

1. **云端沙箱连不上任何店铺**：代理对店铺域名返回 403，WebFetch 也被拦，只有 WebSearch 能用。所有真实抓取都必须在 **GitHub Actions** 上做，用下文的 `check` / `probe` 模式。
2. **GitHub 写权限**：会话一开始 `git push` 和建分支都返回 403。原因是 Claude GitHub App 没装到 `btctrm` 账号上，用户在 claude.ai 的 Connectors → GitHub → Fix 装好之后，同一个会话里就能推送了。现在可以推送、开 PR、合并、触发 Actions，也能读日志。
3. **不能强推**：auto mode 的安全分类器拦截了 `git push --force-with-lease`。每次 squash 合并之后，按这个顺序处理分支：
   ```bash
   git fetch origin main
   git checkout -B claude/gallant-euler-3uzttp origin/main
   git merge -s ours origin/claude/gallant-euler-3uzttp -m "合并已 squash 合入 main 的旧分支历史（内容不变）"
   git branch -u origin/claude/gallant-euler-3uzttp
   git push origin claude/gallant-euler-3uzttp      # 快进，不需要强推
   ```
4. **Python 版本不一致**：沙箱默认是 3.13，Actions 用的是 **3.11**。曾经出过一次 f-string 里带反斜杠、在 3.11 上语法错误的问题（只影响分支，没进 main）。**提交前请用 3.11 跑**：
   ```bash
   /usr/bin/python3.11 -m compileall -q hmon tests && /usr/bin/python3.11 -m pytest -q tests
   ```
   已经给 3.11 装好了 pyyaml、requests、pytest。
5. **在分支上跑 Actions**：
   - `workflow_dispatch` 可以指定 `ref=claude/gallant-euler-3uzttp`，用分支上的代码和 workflow 来跑。
   - `check` 和 `probe` 模式**不会提交 state**（“保存状态”这一步只在 `mode==run` 或定时触发时才执行）。**不要在分支上跑 `mode=run`**，否则会把 state 提交到分支上。
   - 所有运行共用同一个 `concurrency: hiangle-monitor` 组，验收会让正式运行排队，所以尽量短。
6. **仓库是公开的**，Actions 日志所有人都能看。日志里不能出现密钥，`japan.py` 已经在报错信息里把密钥抹掉了。
7. **定时触发方式【未确认】**：Actions 记录里大部分运行是 `workflow_dispatch`，由 `btctrm` 账号大约每 15 分钟触发一次；GitHub 自带的 `schedule` 只零星跑过，比如今天只在 09:06、17:11（UTC）各一次，累计 180 次，而总运行数是 2800+。推测用户用了某个外部定时服务，带着 GitHub token 触发。查过 Actions 运行列表、`.github/workflows/`、README，都没找到这个服务在哪、token 有效期多长。**如果 token 过期，监控会降级成稀疏的 GitHub 定时，而且不会报错。**
8. **Secrets 现状**（从 Actions 日志里的 env 观察到）：
   - 已配置：`SMTP_USER`、`SMTP_PASS`、`MAIL_TO`（Gmail）。
   - 为空：`PUSHPLUS_TOKEN`、`SERVERCHAN_KEY`（用户不要微信）、`EBAY_APP_ID`、`EBAY_CERT_ID`。
   - 未设置：`YAHOO_JP_APPID`、`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`。

---

## 4. 线上运行快照（2026-11-05 03:30，`main` 上的 state）

| 店铺 id | 最近一轮 |
| --- | --- |
| bergfreunde_eu / alpinetrek_uk | 正常：各 45 个尺码，30 个有货 |
| bergzeit | 正常：41 个尺码，27 个有货 |
| spokex | 正常：13 个尺码，4 个有货 |
| delire | 正常：14 个尺码，1 个有货 |
| geartrade | 正常：10 个尺码，1 个有货 |
| trekkinn | 正常：3 个尺码，3 个有货 |
| gearx | 正常：21 个尺码，2 个有货 |
| epictv | 正常：26 个尺码，13 个有货 |
| poshmark | 正常：8 条，8 条在售 |
| sportsshoes | 正常：2 个整款页，0 个有货 |
| ebay_us / ebay_gb / ebay_de | 没有密钥，跳过 |
| yahoo_jp / rakuten | 没有密钥，跳过 |

- **历史上真正推送过的只有 2 条**：
  - 10-30 06:15，SpokeX UK 5（$112，到手 ¥828，利润 ¥112，普通档）。由之前的代码推送。
  - 11-05 03:16，Geartrade 女款 4.5（$38.35，到手 ¥328）。由本会话的迁移逻辑补推，**只发到了邮件**。用户看到邮件后，反馈了排版和成色的问题，PR #3 修了这些。
- **即将推送**：Poshmark 有 6 条二手 listing 达标（到手 ¥326–638），03:30 时确认次数为 1。下一轮确认后会推送，因为超过 5 条，会合并成一封“【6 条上新/降价】”。这些推送里的“预估利润”是按 ¥1050 全新售价算的，**偏高**（见第 9 节第 1 条）。
- 现在全新货离门槛最近的：SpokeX 和 Bergfreunde 差 ¥300 以上；Trekkinn UK 11/11.5 是 ¥984，按冷门码门槛还差 ¥334；EpicTV Pro 是 ¥1030。

---

## 5. 代码改动详解（按文件）

> 现在的函数位置可以用 `grep -n "^def " hmon/*.py hmon/parsers/*.py` 查。

### 5.1 `hmon/notify.py`
- **`delivered(results)`**：只要有一个渠道返回以“成功”结尾的字符串（或者是演练），就算发出去了。
- **`failures(results)`**：列出失败的渠道。
- **Server酱 判定修正**：以前只看 HTTP 200，现在要求返回 JSON 里 `code == 0`。
- **`md_to_html(md)`**：把推送用的简易 Markdown（`### 标题`、`- **键**：值`、`---`、链接）转成带内联样式的 HTML。`send()` 在调用方没传 `html` 时会自动生成，所以**所有邮件都是 HTML 加纯文本两部分**。以前推送邮件只有纯文本，会露出 `###` 和 `**`。

### 5.2 `hmon/run.py`（主流程）
1. **推送失败回滚重发**：
   - `alerts` 的元素变成 `(标题, 正文, [(变体记录, 推送前的 notified_tier)])`。
   - 发送后，如果 `not delivered(res)`，就把 `notified_tier` 改回原值、删掉 `notified_at`，并把 `retry` 加 1，下一轮自动重发；推送里会注明“上次推送失败，第 N 次重发”。
   - 合并推送（超过 `max_separate_alerts` 条）失败时，整批一起回滚。
2. **`note_notify_errors()`**：
   - 有渠道失败时，写入 `meta.notify_error = {time, errors}`，日报“运行情况”里会显示。
   - 每天最多单独发一次“【通知渠道异常】”。
   - **注意**：现在只有邮件一个渠道，邮件本身坏了的话，这条提醒也发不出去（见第 10 节）。
3. **首次扫描时已达标的商品也推送**：
   - 首次扫描一家店时，非推送档位照旧记为基线；推送档位不再静默，而是设 `notified_tier=None`、`baseline_carry=True`，复查一轮后推送，并注明“首次扫描这家店时就已在库，之前没推过”。
   - **`migrate_baseline(st)`** 是一次性迁移，用 `meta.migr_baseline_v1` 标记。它把旧 state 里“在库、档位可推、`notified_tier == tier`、没有 `notified_at`、`first_in <= baseline_at`”的记录改成待推。**线上已经执行过**，推出的就是 Geartrade 那一条。
4. **价格追踪和降价提醒**：
   - **`track_price(v, price, cfg, drops, o, baselined)`**：
     - 连续两轮价格相差在 ±2% 以内，才算“确认价”，取两轮里较高的那个，偏保守。
     - 确认价和参考价 `price_ref` 相差超过 2%，才记入 `price_hist`（最多 20 条）。
     - 新确认价比 `price_ref` 低 `rules.price_drop_pct`（默认 10%）以上，就产生一次降价事件。
     - 首次扫描、第一次确认价时只记录，不报降价。
     - 为什么要 ±2% 的容差：Trekkinn 每次刷新价格会差 $2 左右。
   - **`drop_alerts()`**：
     - 同一店、同一商品、同一配色、同样“旧价 → 新价”的所有尺码，合成一条“【降价 -X%】”。
     - 本轮已经按门槛推过的尺码不会重复推。
     - 只有冷门码降价时只进日报。
     - `rules.price_drop_push: false` 时全部只进日报。
     - 降价事件存在 `meta.price_drops`（最多 30 条），日报列出最近 7 天。
     - 超过 3 条时合并成一条推送。
5. **日报 `digest_text()` 新增内容**：
   - “离门槛最近”前 5 名：按店 + 款 + 配色 + 到手价 + 适用门槛分组，同组尺码合并成一行，写明还差多少钱。
   - “近 7 天明显降价”。
   - 最近一次通知渠道出错的记录。
   - 试运行店铺名后面标“（试运行）”。
   - 新增 **`limit_of(cfg, uk)`**：返回这个尺码适用的门槛。主力码和码制不明用 `normal`（850），其他用 `cold`（650）。
   - `maybe_digest()` 改成用 `delivered()` 判断：日报发送失败，下一轮会补发。
6. **试运行店铺（`trial: true`）**：
   - 读取失败不发“监控失效”或“监控恢复”。
   - `scan_store()` 把 `core.LIMITS` 调成超时 15 秒、不重试，`finally` 里再恢复成 25 秒、重试 2 次。
   - 推送里注明“试运行店铺，解析未经人工验收”。
7. **推送正文 `alert_text()` 重排**（PR #3）：
   - 新顺序：尺码 → 到手成本和预估利润（同一行）→ 标价和店铺运费 → 成色 → 备注 → 链接 → 店铺和配色 → 检测时间加验证说明。
   - 新增 **`size_text(o, scfg)`**：
     - 认得出码制时，显示“EU/UK/美码，后面括号注明店铺原文”，不再重复。
     - 认不出时，显示“码制不明，店铺写‘4.5’”，再附上推测，比如“若是美码女 4.5 ≈ UK 3 / EU 表外；若是美码男 4.5 ≈ UK 4”。推测**只作参考，不参与档位判断**。
8. **命令行**：
   - `check all` 会逐店打印，某一家出异常不影响其他家。
   - 新增 `probe <域名或链接…> [--dump]`。`main()` 改用 `parse_known_args`，所以 `--dump` 可以混在 targets 里。

### 5.3 `hmon/core.py`
- 新增 `LIMITS = {"timeout": 25, "retries": 2}`。`fetch()` 的 `timeout` 和 `retries` 默认从这里读，方便试运行店铺调低。
- 最后一次失败后不再多 sleep 一轮。

### 5.4 `hmon/money.py`
- `evaluate()`：`rules.push_used == false` 时，二手达标也降为 `record`，只进日报。默认 `true`，和之前的行为一致。

### 5.5 `hmon/sizes.py`
- `_norm()` 和 `gender_from_title()` 会把弯引号 `’ ‘` 转成 `'`，这样 “Men’s 11.5” 也能识别。
- `AUTO` 规则支持 “Mens Size 10.5”、“Men's US 9”、“Womens Size 6”。正则是 `\b(Men'?s|Mens|Women'?s|Womens)\s*(?:US\s*)?(?:Size\s*)?([\d.]+)`。

### 5.6 解析器
- **`parsers/shopify.py`**
  - `discover: false`：店铺站内搜索接口用不了时跳过搜索，只读 `handles`。
  - `handles`：写死的商品页列表，SpokeX 和 Délire 已经写死（实测 SpokeX 的站内搜索已经搜不到 Hiangle）。
  - 尺码选项名先精确匹配 `SIZE_OPTION_NAMES`，匹配不到再做“包含”匹配，比如 GearX 的 “Footwear Size (Men's)”。
  - 尺码选项名里带男女标注时，**以选项名为准**判断男女。
  - 有 `compare_at_price` 高于现价时，备注写“原价 X（现价约 N 折）”。
  - 新增 **`_condition_detail(cfg, product)`**，返回 `(成色, 说明)`：
    - 标签 `mm-google-shopping-condition-<grade>`，或描述里的 “in (like new|excellent|good|fair|poor|new) condition”，都会被识别成二手（new 除外）加等级；
    - 描述里 “Product Condition: …” 一直到 “Size:/Color:/Retail Cost:” 之前的磨损说明，截取 160 字附在备注里；
    - `condition: tags` 的店（Geartrade、GearX）没写成色时，备注写“店铺没写成色（标签：70-Off、RetailVendorPartner…），请看商品图”。
    - 这些格式是 2026-11-04 用 probe 实测 Geartrade 得到的。
- **`parsers/jsonld.py`**：新增 `single_offer: true` 模式。页面没有 ProductGroup、只有带 offers 的 Product 时，整款记一条，`variant_id="all"`，`uk=None`，按码制不明处理。支持 AggregateOffer 的 `lowPrice`。用在 SportsShoes。
- **`parsers/poshmark.py`**（新文件）：
  - 流程：搜索页 `https://poshmark.com/search?query=…&type=listings&availability=available` → 从 JSON-LD ItemList 取链接，只保留含 hiangle 的，最多 `max_items` 条（默认 12）→ 逐条打开 listing 页，读 JSON-LD Product。
  - 从 Product 里取 price、availability（InStock / SoldOut）、itemCondition（New / Used）和标题（先 `html.unescape`）。尺码按标题换算。
  - `product_id` 取链接最后一个 `-` 后面的那段。搜索结果里消失的条目记为 `gone_products`，按缺货处理。
- **`parsers/japan.py`**（新文件）：
  - `api: yahoo_jp`：调用 `https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch`，参数 `appid, query, results=50, sort=+price`。读取 `hits[].name / price / url / inStock / code / condition / seller.name`，只保留 `inStock` 的。**【未确认】** 这些字段名来自 Qiita 文章和官方文档的搜索结果，没有拿真实密钥调用过。
  - `api: rakuten`：默认地址 `https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601`，可以用 config 里的 `endpoint` 覆盖。参数 `applicationId`、可选的 `accessKey`、`availability=1`、`formatVersion=2`、`sort=+itemPrice`。**【未确认】** 乐天正在迁移接口（有第三方资料提到 `20260401` 版本和 accessKey），查过 Zenn 和 APIs.io 上的第三方资料，没有核实官方文档。
  - 关键词过滤：标题含 `hiangle / ハイアングル / ハイ アングル`；排除标题含 `キッズ / ジュニア / kids / junior` 的。
  - 日本店一个商品页通常包含多个尺码，所以统一按码制不明处理（标题里写了 UK 或 US 码的除外）。
  - 没有密钥时返回 `ok=True` 并说明“未配置…已跳过”。报错信息会抹掉 `appid / applicationId / accessKey`。

### 5.7 `hmon/probe.py`（新文件）
用来在 Actions 上探测候选店铺，不改状态，也不发通知。
- 只给域名时，按 Shopify 店处理：调用 `suggest.json` 搜索，列出 Hiangle 商品的变体数、跟踪库存数、有货数、价格和原价、选项、尺码样例，以及**标签、类型、描述前 400 字**。
- 给完整链接时：报告是否被拦截、JSON-LD 类型、ProductGroup 逐码样例或 Product.offers 样例、页面里是否含 Hiangle。
- 加 `--dump` 时，额外输出 JSON-LD 开头、内嵌的 JSON（`__NEXT_DATA__` / `application/json`）、`window.*State` 变量，以及**从 `<body>` 开始**截取的 3 段 Hiangle 附近原文。用来给新解析器找数据结构。

### 5.8 `.github/workflows/monitor.yml`
- `mode` 可选值新增 `check`、`probe`；新增两个输入 `store`（默认 `all`）和 `targets`。
- 这两个输入通过环境变量 `IN_STORE` / `IN_TARGETS` 传进脚本，不直接拼进 shell，避免注入。
- 新增注入 `YAHOO_JP_APPID`、`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`。

### 5.9 `config.yaml`
- `rules` 新增 `price_drop_pct: 10`、`price_drop_push: true`、`push_used: true`。
- `profit.forwarder.default` 的注释补充：日本暂时也按 ¥150 算。
- 店铺变化见第 6 节。
- **门槛 `thresholds` 一个数字都没改。**

### 5.10 测试
- `tests/test_logic.py`：原有 12 个，新增 9 个，共 21 个。覆盖推送失败重发、首次扫描好货补推、降价提醒、价格抖动不误报、降价进门槛只推一次、试运行店铺失败静默、迁移、日报离门槛、`push_used` 开关。测试用的假发送函数现在返回 `["测试 成功"]`，设置 `FAIL_SEND` 可以模拟失败。
- `tests/test_parsers.py`（新文件）：6 个用例，覆盖 SportsShoes 整款单价、Bergzeit 的 “UK 4,5” 写法、Poshmark、Yahoo（过滤童鞋和缺货）、乐天没有密钥时跳过、Geartrade 成色解析。
- 合计 **27 个，在 3.11 上全部通过**。

---

## 6. 店铺和渠道清单

### 6.1 现在启用的（`config.yaml`，共 16 个）

| id | 类型 | 状态 | 说明 |
| --- | --- | --- | --- |
| bergfreunde_eu / alpinetrek_uk | bergfreunde | 原有 | 双来源核对 |
| spokex | shopify | 原有，**新写死商品页** | 尺码按 US_M 推测，**【未确认】**，6 周来没人工核对过 |
| delire | shopify | 原有，新写死商品页 | 清仓价 C$161 拿不到，接口给的是原价 C$230，只会漏报 |
| geartrade | shopify, `condition: tags` | 原有 | 寄卖店，PR #3 后能读成色 |
| trekkinn | jsonld | 原有 | 只盯 1 个商品页，3 个尺码 |
| ebay_us | ebay | 原有 | 没有密钥，**从未实测** |
| ebay_gb / ebay_de | ebay | **新增**（PR #1） | 共用 eBay 密钥，从未实测 |
| gearx | shopify, trial | **新增**（PR #1） | 实测能读；尺码选项 “Footwear Size (Men's)/(Women's)”，`size_system: US`；新旧都卖，没打 Used 标签的记成色未知 |
| epictv | jsonld, trial | **新增**（PR #1） | 实测能读；尺码写成 “38 2/3” 这种不带 EU 前缀的欧码，`size_system: EU`；价格随访问地区变化，GitHub 服务器在美国，所以给的是美元 |
| bergzeit | jsonld, trial | **新增**（PR #2） | 3 个商品页（男款 3007435、女款 3007436、Pro 3008209），尺码写 “UK 6” |
| sportsshoes | jsonld + `single_offer`, trial | **新增**（PR #2） | 英国站 fiv238 £59.99（原价 £119.99），德国站 fiv131 €49.59。都缺货，补货后到手约 ¥620，会触发推送 |
| poshmark | poshmark, trial | **新增**（PR #2） | 每轮最多 13 次请求（1 次搜索 + 12 条 listing） |
| yahoo_jp | japan, trial | **新增**（PR #2） | 等 `YAHOO_JP_APPID` |
| rakuten | japan, trial | **新增**（PR #2） | 等 `RAKUTEN_APP_ID`，接口地址【未确认】 |

### 6.2 探测过、没有接入的（都在 Actions 上实测过）

| 结果 | 渠道 |
| --- | --- |
| 403 被拦截 | Snowleader、Bike24、Sierra、Mercari 美国、（之前就有的）BananaFingers、Adidas 官网、Backcountry、Oliunid、SportScheck、ZOZO |
| 商品页 404 | Sportfits（站内搜索接口也是 404）、Neptune Mountaineering |
| 页面没有逐码数据 | Varuste.net、Barrabes、Absolute-Snow、Hardloop（有一个 `api-shop.hardloop.fr/api/v2/products/<id>` 接口，但里面只有商品信息，没有库存和价格）、Klimschoenen（比价站） |
| 不是 Shopify | Climbing Anchors、Snap Climbing、Wild Earth、Altitude Sports、Last Hunt |
| 其他 | CampSaver（返回非 JSON 的拦截页）、Steep & Cheap（HTTP 202）、goofee.shop（417）、mountaingear.com（域名解析失败）、乐天和 Yahoo 网页版（被拦，只能走接口） |
| Shopify 能读但没卖 Hiangle | Rock+Run、Climb On Equipment、Bivouac |
| 能打开但暂缓 | **Kleinanzeigen**（JSON-LD 里只有带标题的 ImageObject，价格在 Astro 渲染的正文里，要单独写解析器）、**Vinted**（数据在浏览器端加载） |

---

## 7. state.json 新增字段

| 位置 | 字段 | 含义 |
| --- | --- | --- |
| `variants.*` | `price_last` | 上一轮的价格 |
| | `price_ref` | 最近一次确认的参考价 |
| | `price_hist` | `[[时间, 价格], …]`，最多 20 条 |
| | `retry` | 推送失败的重发次数，成功后删除 |
| | `baseline_carry` | 首次扫描时就已达标、等待补推，推送后删除 |
| `meta` | `migr_baseline_v1` | 一次性迁移已执行，线上已经是 true |
| | `notify_error` | `{time, errors}`，最近一次渠道错误 |
| | `notify_error_day` | 渠道异常提醒当天已经发过的标记 |
| | `price_drops` | 降价事件，最多 30 条 |

旧字段都没改，可以和旧数据兼容。

---

## 8. 验证记录（Actions 运行 ID）

| 运行 ID | 内容 |
| --- | --- |
| 41890274188 | 分支 `check all`：原有 6 家全部正常；第一批试运行店铺里 EpicTV 能读，其他失败 |
| 41890728629 | 分支 `probe` 14 个候选：找到 GearX |
| 41891129717 | 分支 `check all`：GearX 和 EpicTV 尺码换算核对无误 |
| 41893901096 | `main` 上 `probe` 15 个折扣和综合渠道：Bergzeit 可用，SportsShoes 只有整款单价 |
| 41894417430、41894732060 | 分支 `probe --dump`：拿到 Poshmark、Kleinanzeigen、Bergzeit、Hardloop、SportsShoes 的页面结构 |
| 41895143013 | 分支 `check all`，16 家：Bergzeit、SportsShoes、Poshmark 读取正常，日本两家跳过 |
| 41895159734 | **PR #1 合并后第一轮正式运行**：Geartrade 补推，邮件发送成功 |
| 41896786333 | **失败**：probe 在 Python 3.11 上 f-string 语法错误（已修复，没进 main） |
| 41897134771 | 分支 `probe geartrade.com gearx.com`：拿到 Geartrade 的成色标签和描述格式 |

新版推送邮件的排版用 Playwright 渲染核对过。

---

## 9. 已知问题、风险和未确认事项

1. **利润模型和用户的诉求有冲突（最重要）**：
   - 档位只看到手成本，转运费和利润都不参与判断。按现在的规则，普通档在美国店利润最低 ¥90 也会推，其他国家最低 ¥40 也会推。10-30 那次 SpokeX 推送，利润只有 ¥112。
   - 二手也按 ¥1050 全新售价算利润，所以 Poshmark 显示的利润 ¥300–600 偏高。
   - 修复方向见第 10 节第 1 条，**需要用户先给数字**。
2. **只有邮件一个通知渠道**：Gmail 应用密码失效时，“通知渠道异常”提醒也是走邮件发，等于发不出去。现在只能靠“每天早上有没有收到日报”来判断系统是否正常。
3. **外部定时触发【未确认】**：见第 3 节第 7 条。
4. **eBay 解析器从未实测**（之前的 AI 写的，本会话只加了英、德两站的配置）。
5. **Yahoo 字段名、乐天接口地址都【未确认】**：有了密钥之后，先跑 `check yahoo_jp` / `check rakuten`。
6. **尺码换算只是推测**：
   - SpokeX、Délire 按 US_M 推测；
   - Geartrade 的 “4.5”“41.5” 这类写法记为码制不明；
   - Poshmark 按卖家标题换算，可能写错；
   - 日本和 SportsShoes 统一按码制不明处理。
7. **SportsShoes 整款有货不等于有你要的码**：任何一个尺码有货就算有货，所以可能推出一条实际上没有合适尺码的提醒，按 ¥850 码制不明线判断。
8. **Poshmark 每轮 13 次请求**：有被封的风险。它是试运行店铺，被封了也只会静默失败。
9. **运费和转运费都是估算**：各店的 `shipping` 是估的；非美国转运费 ¥150 是占位数（日本也是）。
10. **价格随地区变**：EpicTV 按访问地区给币种和价格，GitHub 服务器在美国，所以拿到的是美元价。
11. **Geartrade $38.35 女款**（product `five-ten-hiangle-climbing-shoe-womens-987564`）：店铺数据里没有成色，用户确认是二手、磨损很少；仍然在售，已推送过，没有加进 ignore。
12. **state 提交频繁**：每 15 分钟一次提交，历史增长很快，但功能上没有影响。日报也比较长。
13. **`TASKS.md` 的旧问题**：第 16 项此前没打勾，“读不了的店”里误列了 SportsShoes。本次交接时已经一并更正。

---

## 10. 待办和建议（按投入产出比排序）

**等用户回答（阻塞第 1 条）：**
- 最低利润线 `min_profit` 定多少（建议 ≥ ¥150，可以再加一点丢件风险预留）？
- 二手 Hiangle 实际能卖多少 `used_sale_price`？

**高 ROI：**
1. **加 `rules.min_profit`，并给二手单独设 `profit.used_sale_price`**：在 `money.evaluate()` 里，利润低于 `min_profit` 的降为 `record`；二手用 `used_sale_price` 算利润。约 10 行代码，再补测试。
2. **邮件渠道兜底**：在 `run()` 里，如果本轮有推送而且全部渠道都失败，最后以非零退出码结束。这样 Actions 这一轮会标红，GitHub 会用自己的通知系统给用户发邮件，不依赖用户的 SMTP。注意要先保存 state 再退出（workflow 里“保存状态”这一步要改成 `if: always()`，或者把 state 保存提前）。
3. **用户自己申请密钥**：
   - eBay 开发者密钥，一套同时开通美国、英国、德国三站；
   - Yahoo 日本 Client ID：日本常规价约 19,800 日元（约合 ¥950），打 8–9 折或叠加积分就接近门槛。
   - 建议在黑五（2026-11-27）之前弄好。拿到密钥后先跑 `check`。

**中 ROI：**
4. 让用户人工核对 SpokeX、Délire 一个尺码的标注，核对通过后把 `size_verified` 改成 true；试运行店铺验收通过后删掉 `trial`。
5. 探测比价聚合站：idealo.de、geizhals、PriceRunner。**都还没测**，一个站可能覆盖几十家店。
6. 每家店加一个可选的 `extra_discount`，用来计入积分、订阅首单折扣（比如日本积分、Bergzeit 订阅优惠）。
7. Trekkinn 补上 Pro 款和其他配色的商品链接。

**低 ROI，暂时不做：** Kleinanzeigen、Vinted 解析器；Délire 清仓价；减少 state 提交；精简日报。

---

## 11. 常用操作

```bash
# 本地测试（务必用 3.11，和 Actions 一致）
/usr/bin/python3.11 -m compileall -q hmon tests && /usr/bin/python3.11 -m pytest -q tests

# 离线演练（沙箱里抓取会全部失败，只用来检查流程不崩）
python3 -m hmon run --dry-run --state <临时 state 路径>
python3 -m hmon digest
```

在 Actions 上验证（用 GitHub MCP 的 `actions_run_trigger`，`workflow_id=monitor.yml`，`ref` 填分支名）：
- 逐码验收：`inputs={"mode":"check","store":"all"}`（`store` 也可以填单个店铺 id）
- 探测新店：`inputs={"mode":"probe","targets":"域名 或 完整链接 …"}`；需要页面样本时，在 targets 里加 `--dump`
- 发测试通知：`inputs={"mode":"test-notify"}`
- 看结果：`actions_list(list_workflow_runs / list_workflow_jobs)` → `get_job_logs(job_id, return_content=true, tail_lines=N)`

新增一家店的流程：
1. `probe` 判断用哪个解析器：Shopify → `shopify`；有 ProductGroup → `jsonld`；只有整款 Product → `jsonld` 加 `single_offer`。
2. 在 `config.yaml` 里加配置，标 `trial: true`。
3. 在分支上跑 `check <id>`，对照真实网页核对尺码。
4. 开 PR 合并。
5. 让用户验收，通过后删掉 `trial`。

---

## 12. 本会话的提交（不含机器人的 state 提交）

合并进 main 的 3 个 squash 提交：`5cd4372`（#1）、`0610de0`（#2）、`67ab28e`（#3）。分支 `claude/gallant-euler-3uzttp` 上还保留着逐条提交，用 `git log --oneline origin/claude/gallant-euler-3uzttp | grep -v " state "` 查看。主要包括：

- 增加探测命令和验收模式
- 推送失败重发、基线补推、降价提醒、日报离门槛排名、7 家试运行店铺
- 按 Actions 实测结果调整店铺（EpicTV 改欧码、写死商品页、删掉读不了的店）
- 新增 GearX，Shopify 尺码选项模糊匹配
- probe 加 `--dump`，样本从正文开始截取
- 日本接口、整款单价页面、Poshmark 解析器，以及 5 个离线测试
- 识别 “Mens Size 10.5” 和弯引号写法，新增 `push_used` 开关
- 推送邮件改 HTML，码制不明附推测
- 修复 probe 在 3.11 上的 f-string 语法错误
- 推送顺序调整，寄卖店读取成色

本交接报告（`HANDOFF.md`）和更正后的 `TASKS.md`，通过 PR #4 合并。
