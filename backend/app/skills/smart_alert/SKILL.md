---
name: smart-alert
description: 根据异常检测结果，智能生成分级预警（P0/P1/P2），匹配通知模板并推送给相关负责人
triggers:
  - event: anomaly_detected from sales-anomaly-detection
  - manual: user triggers alert review
depends_on:
  - sales-anomaly-detection (Skill)
  - resources/templates.json
---

# 智能预警技能

## 目标
当检测到销售异常时，根据异常级别自动生成结构化预警通知，匹配通知模板，并通过企业 IM 或邮件推送。

## 预警级别定义

| 级别 | 条件 | 响应时间 | 通知方式 |
|------|------|----------|----------|
| P0 | GMV 偏离 > 50% 或 Z-Score > 3 | 5 分钟内 | 电话 + 飞书 + 邮件 |
| P1 | GMV 偏离 30%-50% 或 Z-Score 2-3 | 15 分钟内 | 飞书 + 邮件 |
| P2 | GMV 偏离 15%-30% | 1 小时内 | 飞书消息 |

## 工作流程

### Step 1: 接收异常事件
从 `sales-anomaly-detection` Skill 接收异常判定结果，提取：异常指标、偏离度、严重级别、可能原因。

### Step 2: 匹配通知模板
从 `resources/templates.json` 加载通知模板，根据级别和异常类型选择对应模板，填充实际数据。

### Step 3: 生成预警内容
结构化预警包含：
- 标题：[P0/P1/P2] {异常指标}异常告警
- 摘要：{指标}当前值{xxx}，偏离{xx%}
- 详情：时间、影响范围、可能原因
- 建议：AI 生成的下一步行动建议

### Step 4: 推送通知
调用通知接口（飞书 Webhook / 钉钉机器人 / 邮件 API）发送预警。

## 通知模板示例
```
🚨 [P0] GMV异常告警
时间: 2026-06-17 14:35
指标: GMV 5分钟均值
当前值: ¥52,000
预期值: ¥98,000
偏离: -46.9%
可能原因: 支付系统故障 / 竞品大促
建议: 立即排查支付链路，检查系统监控面板
```
