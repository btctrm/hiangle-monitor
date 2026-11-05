# 优化任务清单（2026-11-04）

- [x] 1. 通知发送失败不算“已推送”，下一轮重试；渠道出错每天提醒一次、写进日报
- [x] 2. 日报增加“离门槛最近”前 5 名（按店+款+价合并尺码）和“近 7 天明显降价”
- [x] 3. 基线时就已达标的商品也推一次；一次性迁移旧状态（会推 Geartrade $38 女款 4.5 码）
- [x] 4. 价格历史 + 明显降价提醒（两轮确认、±2% 抖动不算）
- [x] 5. 新增店铺：在 Actions 上实测 20 多家，留下能读且卖 Hiangle 的 GearX、EpicTV
- [x] 6. eBay 增加英国站、德国站（同一套密钥）
- [x] 7. Actions 增加 check（逐码验收）和 probe（探测新店）模式
- [x] 8. 本地测试 20 个全部通过；Actions 上 check 全部店铺读取正常
- [x] 9. 推送到 GitHub 分支 claude/gallant-euler-3uzttp（已修复 GitHub App 授权）
- [x] 10. 合并到 main（btctrm/hiangle-monitor#1）
- [ ] 11. 申请 eBay 开发者密钥（EBAY_APP_ID / EBAY_CERT_ID），三个 eBay 站一起生效
- [x] 12. 人工看一眼 Geartrade $38.35 女款 4.5 码：用户确认是二手、磨损很少（店铺数据没写成色）
- [ ] 13. 人工核对 GearX、EpicTV 的尺码（实测换算：GearX 美码男 12 = UK 11.5；EpicTV 欧码 42 = UK 8），通过后删掉 trial

- [x] 14. 第二批渠道：探测 30+ 个折扣/综合/二手/日本渠道，接入 Bergzeit、SportsShoes（清仓）、Poshmark、Yahoo!购物、乐天
- [ ] 15. 申请日本接口密钥：YAHOO_JP_APPID（推荐，接口稳定）、RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY
- [x] 16. 第二批合并到 main（btctrm/hiangle-monitor#2）
- [x] 17. 推送邮件改 HTML、寄卖店读取成色、码制不明附推测码数（btctrm/hiangle-monitor#3）
- [x] 18. 写交接报告 HANDOFF.md
- [x] 19. 用户定了：最低利润线 ¥150、二手售价 ¥800 → 已改 money.evaluate()（2026-11-05）
- [ ] 20. 邮件是唯一渠道：全部渠道失败时让 Actions 标红，借 GitHub 自己的通知兜底
- [x] 21. 外部定时触发是 cron-job.org，每 15 分钟调一次 workflow_dispatch；token 是 fine-grained，用户 10-08 建的时候选了“不过期”（10-08 的会话记录里有）

- [x] 22. 合并 10-09 扩展版：新增 54 个来源（新品店 16、比价站 10、二手 22、eBay 6 站），全部 trial（2026-11-05）
- [x] 23. 新规则：有使用痕迹的二手只进日报（push_conditions），比价站码制不明只进日报，低频来源 every_minutes
- [x] 24. 日报改成每个来源一行概况（几百个有货尺码会超过 Gmail 102KB 被截断）
- [x] 25. Yahoo!オークション 改版成 Next.js，解析器已改读 __NEXT_DATA__，并读取平台成色（USED10=近新）
- [x] 26. 测试 33 个全部通过（3.11）；沙箱里用线上 state 演练两轮，没有误推，第二轮会推 2 条（Willhaben €66 全新 UK6、Jimoty ¥15,000 全新 23.5cm）
- [ ] 27. 用户把新 zip 拖到 GitHub 上传页部署；部署后看第一轮哪些来源在 GitHub 上读不了
- [ ] 28. 沙箱里读不了、要在 GitHub 上确认：PriceRunner 英/瑞/丹、beslist、Backcountry（HTTP 202 挑战页）、BigGo（找不到数据）、EpicTV（沙箱 403，GitHub 上之前能读）
- [ ] 29. 第 20 项要改 workflow，上传 zip 改不了 .github；需要用户把仓库授权给本会话（或手动改）

## 新发现的事项
- [ ] 日本转运费没有报价，暂按 ¥150；有实际报价请改 config.yaml 的 forwarder
- [x] Kleinanzeigen（德国二手）：10-09 版已有专门解析器，这次一并接入
- [ ] Vinted 数据在浏览器端加载，免费方案读不了
- [x] SpokeX 站内搜索已搜不到 Hiangle（之前靠记住的商品页在读），已写死商品页
- [ ] SpokeX / Délire / Geartrade 尺码换算仍是推测，待人工验收
- [ ] Délire 清仓价（C$161）接口拿不到，只会漏报
- [ ] GearX 新旧都卖，没打 Used 标签的记“成色未知”
- [ ] EpicTV 页面价格随访问地区变（GitHub 服务器在美国，给的是美元）
- [ ] Bergfreunde/Alpinetrek 的 Hiangle Pro UK 13.5/14.5 标价 €79.98/£68.48（缺货），补货的话到手约 ¥666，离冷门码门槛 ¥650 很近
- [ ] Trekkinn 只盯了 1 个商品页，Pro 款和其他配色没覆盖
- [x] 门槛（¥750 / ¥850）：用户决定保持不变，宁高勿低；改为另加最低利润线（第 19 项）
- [x] 读不了的店（已删）：Snowleader、Bike24、Sierra、Mercari（403）；Varuste、Barrabes、Absolute-Snow、Hardloop、Klimschoenen（无逐码数据）；Sportfits、Neptune（404）；澳洲几家、Altitude Sports、Last Hunt（非 Shopify）。SportsShoes 后来用“整款单价”模式重新接入了
- [ ] Poshmark 6 条二手即将合并推送；利润按 ¥1050 算偏高（见第 19 项）
- [x] 比价聚合站：PriceRunner、billiger、beslist 等 10 个已接入；idealo 被拦（10-09 调研）
- [ ] 日本 cm→UK 换算按 UK = cm − 18.5（来自 Goofee 尺码表），没拿 adidas 日本官方表核对
- [ ] Addnature“页面列出的尺码 = 有货”是推断；Hardloop 供应商调货算有货（备注写到货日期）
