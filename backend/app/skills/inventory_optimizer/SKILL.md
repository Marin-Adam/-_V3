---
name: inventory-optimizer
description: 结合销售趋势与当前库存水位，智能生成补货建议和清仓预警，优化库存周转效率
triggers:
  - scheduled: every 30 minutes
  - manual: user asks about inventory or replenishment
depends_on:
  - query_inventory (MCP)
  - query_sales_metrics (MCP)
  - resources/inventory_model.py
---

# 库存优化技能

## 目标
基于实时销售数据和当前库存水位，计算库存周转天数，预测缺货风险，自动生成补货计划或清仓建议。

## 工作流程

### Step 1: 获取数据
调用 MCP 工具：
- `query_inventory(alert_only=false)` — 获取所有商品库存
- `query_sales_metrics(time_range="24h")` — 获取近期销售数据

### Step 2: 计算关键指标
对每个 SKU：
1. **日均销量** = 过去 24 小时订单量 / 1天
2. **可售天数** = 当前库存 / 日均销量
3. **周转状态**判定：
   - 可售天数 < 3 → 紧急补货
   - 可售天数 3-7 → 建议补货
   - 可售天数 7-30 → 库存健康
   - 可售天数 > 30 → 库存过剩，建议清仓

### Step 3: 生成优化建议
根据周转状态生成具体建议：
- **紧急补货**：建议补货量 = (安全库存天数 - 可售天数) × 日均销量
- **建议补货**：推荐补货时机和数量
- **库存过剩**：建议促销清仓策略（折扣力度、预期清仓周期）

### Step 4: 输出报告
结构化输出每个 SKU 的库存健康度报告，按紧急程度排序。

## 安全库存模型
`safety_stock = z_score × σ_demand × √lead_time + avg_demand × lead_time`
- z_score = 1.65 (95% 服务水平)
- lead_time = 3 天 (默认补货周期)
- σ_demand = 需求标准差

## 使用方法
- 定时触发：每 30 分钟自动评估
- 手动触发：用户问"哪些商品需要补货"或"库存健康度怎么样"
