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
- [ ] 10. **合并到 main 才会生效**（定时任务只跑 main）——等你确认后开 PR
- [ ] 11. 申请 eBay 开发者密钥（EBAY_APP_ID / EBAY_CERT_ID），三个 eBay 站一起生效
- [ ] 12. 人工看一眼 Geartrade $38.35 女款 4.5 码（成色未知、码制不明；原价 $160）
- [ ] 13. 人工核对 GearX、EpicTV 的尺码（实测换算：GearX 美码男 12 = UK 11.5；EpicTV 欧码 42 = UK 8），通过后删掉 trial

## 新发现的事项
- [x] SpokeX 站内搜索已搜不到 Hiangle（之前靠记住的商品页在读），已写死商品页
- [ ] SpokeX / Délire / Geartrade 尺码换算仍是推测，待人工验收
- [ ] Délire 清仓价（C$161）接口拿不到，只会漏报
- [ ] GearX 新旧都卖，没打 Used 标签的记“成色未知”
- [ ] EpicTV 页面价格随访问地区变（GitHub 服务器在美国，给的是美元）
- [ ] Bergfreunde/Alpinetrek 的 Hiangle Pro UK 13.5/14.5 标价 €79.98/£68.48（缺货），补货的话到手约 ¥666，离冷门码门槛 ¥650 很近
- [ ] Trekkinn 只盯了 1 个商品页，Pro 款和其他配色没覆盖
- [ ] 门槛（¥750 / ¥850）比现在所有全新货的到手价低 25–35%，要不要改成“按利润”判断，等你决定
- [ ] 读不了的店（已删）：Snowleader、Bike24（403）；Varuste、SportsShoes、Barrabes、Absolute-Snow（无逐码数据）；Sportfits、Neptune（404）；澳洲几家、Altitude Sports（非 Shopify）
