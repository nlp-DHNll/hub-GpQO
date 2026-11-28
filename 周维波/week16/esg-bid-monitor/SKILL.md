---
name: esg-bid-monitor
description: "ESG / 可持续发展 / 双碳招投标信息汇总与监控 Skill：回溯汇总近两年相关中标项目，分析热点品类、客户类型、地区与中标金额分布、供应商格局；并每日采集新增招标/中标信息，去重打分后生成推送清单。当用户要求汇总 ESG 咨询、碳核算、碳足迹、双碳规划、绿色金融、ESG 报告编制等中标/招标项目，分析中标金额分布与热点趋势，或建立每日 ESG 招标信息监控推送时使用。"
---

# ESG 投标信息汇总与监控

## Overview
两条工作线：**历史回溯**——自主检索近两年 ESG/可持续/双碳相关中标公告，经标准化脚本完成金额解析、品类归类与去重，聚合分析金额分布、品类/客户/地区/供应商格局与趋势；**每日监控**——采集新增招标与中标信息，与存量库比对去重、按相关度打分，生成每日推送简报。研判与机会分析由 Agent 结合统计结果撰写。

## 工作流

### A. 历史汇总（近两年）
1. **检索采集**：按 `references/bid-sources.md` 的信源与关键词，从政府采购网、企业采购平台、公共资源交易中心与聚合站点检索；金额与中标方以官方公告为准。每条记录字段：`project, buyer, winner, amount_raw/amount_wan, date, region, category, bid_type, url, summary`。
2. **标准化**：
   ```bash
   python scripts/normalize_bids.py --input raw-bids.json --out normalized.json
   ```
   脚本完成金额解析（统一万元）、品类与客户类型归类、金额分档、键值去重。
3. **聚合分析**：
   ```bash
   python scripts/analyze_bids.py --input normalized.json --out analysis.json \
       --report analysis.md
   ```
   输出概览、金额分档、品类/客户类型/地区/中标方聚合与月度趋势；在 `analysis.md` 骨架上按 `references/analysis-framework.md` 撰写热点研判。

### B. 每日监控推送
1. 采集当日新增招标/中标公告，整理为同结构 JSON。
2. 去重打分并生成推送简报：
   ```bash
   python scripts/daily_watchlist.py --new today.json --known known.json \
       --out-list new.json --report daily-brief.md --known-out known.json
   ```
   脚本剔除已收录条目，按 ESG/双碳关键词命中打分排序，输出项目、采购人、供应商、金额、地区、日期、命中标签与链接；`--known-out` 更新存量库供次日比对。
3. 对高相关度条目补充推荐理由与机会判断；未披露金额不估算。

## 参考资源
- `references/bid-sources.md`：信源清单、关键词体系、采集字段与品类/客户分类规则。
- `references/analysis-framework.md`：金额分档口径、分析维度、报告结构与数据纪律。
- `scripts/normalize_bids.py`：金额解析、归类与去重。
- `scripts/analyze_bids.py`：分布聚合与趋势统计。
- `scripts/daily_watchlist.py`：每日新增去重、打分与推送清单。
- `assets/sample-bids.json`：近两年真实中标样例（含未披露金额条目）。
