---
name: competitor-monitor
description: 定时监控竞品价格与促销活动，自动对比我方价格竞争力，生成竞品动态报告
triggers:
  - scheduled: every 5 minutes
  - manual: user asks about competitors
depends_on:
  - query_competitor_prices (MCP)
  - execute_analytics_query (MCP)
---

# 竞品监控技能

## 目标
定时抓取竞品价格数据，对比我方定价，识别竞品促销活动，在竞品大幅降价或推出新促销时及时预警。

## 工作流程

### Step 1: 获取数据
调用 MCP 工具：
- `query_competitor_prices()` — 获取最新的竞品价格数据
- 对比我方价格计算价差

### Step 2: 价格对比分析
对每个 SKU：
1. 计算最低竞品价 vs 我方价格的价差百分比
2. 标记"价格劣势"商品（我方价格高于竞品 > 10%）
3. 标记"有竞争力"商品（我方价格低于所有竞品）

### Step 3: 促销识别
从竞品数据中识别：
- 大幅降价（单次降幅 > 15%）
- 限时促销活动模式（连续低价持续一段时间）
- 新品上市（竞品出现新 SKU）

### Step 4: 生成报告
输出结构化竞品分析报告，包含：
- 价格竞争力总览（劣势商品数 / 有竞争力商品数）
- Top 5 价差最大商品
- 竞品促销活动提醒
- 定价调整建议

## 使用方法
- 定时触发：每 5 分钟自动更新竞品数据
- 手动触发：用户问"竞品最近有什么动作"或"我们的价格有竞争力吗"
