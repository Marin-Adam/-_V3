---
name: sales-anomaly-detection
description: 实时检测电商核心销售指标（GMV、订单量、转化率）的异常波动，并自动生成分析报告
triggers:
  - scheduled: every 5 minutes
  - manual: user asks about sales anomaly
depends_on:
  - query_sales_metrics (MCP)
  - execute_analytics_query (MCP)
---

# 销售异常检测技能

## 目标
实时监控来自 MCP 接口的销售数据流，识别 GMV、订单量、转化率等关键指标的异常波动，自动判定异常严重级别并生成分析报告。

## 工作流程

### Step 1: 获取数据
调用 MCP 工具获取数据：
- `query_sales_metrics(time_range="1h")` — 获取最近 1 小时销售概况
- `execute_analytics_query(metric="gmv", dimension="channel")` — 获取各渠道 GMV 分布
- `execute_analytics_query(metric="orders", dimension="category")` — 获取各品类订单量

### Step 2: 执行检测
运行 `scripts/detector.py` 中的算法：
1. **同比偏离检测**：对比当前 5 分钟 GMV 与过去 1 小时均值的偏离度
2. **Z-Score 检测**：计算当前值偏离历史均值的标准差倍数
3. **趋势突变检测**：检测连续 3 个时间窗口的单调上升/下降

### Step 3: 判定异常级别
- **P0 (严重)**：偏离度 > 50% 或 Z-Score > 3，需立即响应
- **P1 (警告)**：偏离度 30%-50% 或 Z-Score 2-3，需关注
- **P2 (提示)**：偏离度 15%-30%，记录观察

### Step 4: 生成报告
结构化输出：
```json
{
  "anomaly_detected": true/false,
  "severity": "P0/P1/P2",
  "metric": "gmv",
  "current_value": 125000,
  "expected_value": 98000,
  "deviation_pct": 27.5,
  "possible_causes": ["大促活动", "爆品上线", "竞品降价", "系统故障"],
  "recommendation": "建议xxx"
}
```

## 使用方法
- 定时触发：系统每 5 分钟自动执行
- 手动触发：用户问"今天销售有异常吗"或"分析一下GMV为什么下降"
