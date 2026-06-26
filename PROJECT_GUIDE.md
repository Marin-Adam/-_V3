# AI-Native 电商实时监控智能决策平台 — 项目深度指南

> 面试准备专用 · 覆盖架构设计、技术决策、代码实现、面试话术

---

## 目录

1. [一句话概述](#1-一句话概述)
2. [解决的问题](#2-解决的问题)
3. [系统架构](#3-系统架构)
4. [技术栈与选型理由](#4-技术栈与选型理由)
5. [核心模块深度解析](#5-核心模块深度解析)
6. [关键数据流](#6-关键数据流)
7. [代码结构](#7-代码结构)
8. [技术决策与权衡](#8-技术决策与权衡)
9. [面试话术](#9-面试话术)
10. [高频追问与应答](#10-高频追问与应答)

---

## 1. 一句话概述

> 基于 **Agent Skills + MCP 协议**双轮驱动的新一代电商实时监控平台——让 AI 从"被动等查询"升级为"主动思考、自主分析"的智能决策核心。

---

## 2. 解决的问题

### 传统看板的三大痛点

| 痛点 | 传统方式 | 本项目方案 |
|------|----------|-----------|
| **"人找数据"** | 运营盯着图表等异常 | AI Agent 持续监控，**主动发现并推送**异常 |
| **"工具碎片化"** | 查订单、看流量、对竞品需切换 N 个系统 | MCP 协议统一 6 个工具，Agent 自主调用 |
| **"分析靠人"** | 异常出现了，靠运营经验判断原因 | Agent 自动拉数据 + 运行 Skills 算法，秒级出分析报告 |

### 核心差异化

```
传统看板:  数据 → 人眼 → 人脑分析 → 决策        (被动)
本项目:    数据 → Agent自主发现 → MCP取数 → Skills分析 → 输出建议  (主动)
```

---

## 3. 系统架构

### 3.1 分层架构图

```
┌─────────────────────────────────────────────────────────┐
│                  展示层 (Vue 3 + ECharts)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │实时大屏  │ │AI对话    │ │预警中心  │ │Skills配置│   │
│  │Dashboard │ │AgentChat │ │Alerts    │ │Settings  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                      ↕ SSE / REST                       │
├─────────────────────────────────────────────────────────┤
│                  API 网关 (FastAPI)                      │
│  /dashboard  /agent  /alerts  /admin  /mcp             │
├─────────────────────────────────────────────────────────┤
│              Agent 智能体内核                            │
│  ┌──────────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ 意图识别     │ │ 工具调度   │ │ 报告生成        │  │
│  │(关键词/LM)   │ │(MCP调用)   │ │(模板/LM)        │  │
│  └──────────────┘ └────────────┘ └──────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │        Skills 技能库 (4个即插即用技能包)         │  │
│  │  sales-anomaly │ smart-alert │ competitor │ inv-opt │
│  └──────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────┤
│              MCP 协议适配层 (JSON-RPC 2.0)              │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────────────┐  │
│  │销售指标│ │流量数据│ │库存查询│ │竞品价格·订单·分析│  │
│  └────────┘ └────────┘ └────────┘ └────────────────┘  │
├─────────────────────────────────────────────────────────┤
│            模拟数据引擎 (asyncio 并发)                   │
│  订单流(2s)  流量流(10s)  库存流(30s)  竞品流(5min)   │
│            + 异常注入控制器 (随机触发)                  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Agent Skills 的核心设计理念

Skills 不是简单的"插件"——它是 **"即插即用的专业知识包"**，每个 Skill 包含：

```
skills/sales_anomaly/
  SKILL.md            ← 工作流定义（LLM 可读的指令）
  scripts/detector.py ← 可执行算法（Z-Score、偏离度）
  resources/          ← 数据文件（模板、模型参数）
```

**设计哲学**：复制文件夹 = 安装新能力，删除文件夹 = 卸载能力。做到了真正的"热插拔"。

---

## 4. 技术栈与选型理由

| 层级 | 选择 | 为什么这样选 | 对比方案 |
|------|------|-------------|----------|
| **后端框架** | FastAPI | 原生 async/await，自动 OpenAPI 文档，性能接近 Node.js | Flask(同步阻塞)、Django(太重) |
| **Agent 框架** | 自研轻量引擎 | 避免 LangChain 黑盒，完全掌控意图识别→工具调用→报告生成链路 | LangChain(过度抽象)、LangGraph(学习成本高) |
| **MCP 协议** | JSON-RPC 2.0 + HTTP | 标准化工具接口，兼容 Claude Desktop 等 MCP Client；HTTP 比 stdio 更易调试 | REST(无标准)、gRPC(太重) |
| **Skills 加载** | 文件系统扫描 + YAML | 零数据库依赖，Folder=folder Skill，天然支持 Git 版本管理 | DB存储(不够直观)、API注册(耦合) |
| **前端** | Vue 3 + ECharts + Element Plus | 响应式数据绑定适合实时看板，ECharts 生态丰富 | React(学习曲线)、D3(太底层) |
| **实时数据** | asyncio + 内存队列 + SSE | 无中间件依赖，内存数据满足 MVP；SSE 天然单向推送 | Kafka(运维重)、WebSocket(双向不需要) |
| **数据库** | PostgreSQL + pgvector | 关系型 + 向量检索一体，减少组件数量 | Milvus(需要额外部署)、SQLite(不支持向量) |

### LLM 双模式设计

```
有 API Key → LLM 模式（ReAct Agent + Function Calling + GPT-4o/Qwen）
无 API Key → Fast 模式（关键词意图识别 + MCP调数 + 模板生成报告）
```

**关键点**：Fast 模式不只是 fallback——它本身就是一种生产可用的方案，响应时间 < 3 秒，不产生 API 费用。

---

## 5. 核心模块深度解析

### 5.1 数据引擎 (`data/generator.py`)

**设计思路**：用一个后台 asyncio 协程池模拟四条数据流，每条流独立运行、独立推送。

```python
class DataGenerator:
    async def start(self):
        self._tasks = [
            asyncio.create_task(self._generate_orders()),     # 每 1-5 秒
            asyncio.create_task(self._generate_traffic()),    # 每 10 秒
            asyncio.create_task(self._generate_inventory()),  # 每 30 秒
            asyncio.create_task(self._generate_competitor_data()), # 每 5 分钟
            asyncio.create_task(self._anomaly_controller()),  # 随机注入异常
        ]
```

**关键设计决策**：

| 决策 | 选择 | 原因 |
|------|------|------|
| 内存存储 vs 数据库 | 内存 | MVP 阶段快速验证，内存队列足够支持 Demo |
| 推 vs 拉 | **推模式**（SSE 广播） | 实时看板需要推，轮询会浪费资源 |
| 异常注入 | 随机触发（30%概率/2-5分钟） | 模拟真实世界的偶发异常，测试 Agent 检测能力 |
| 并发模型 | asyncio.Task + 独立协程 | 每个流独立崩溃不影响其他流 |

### 5.2 MCP 协议层 (`mcp/`)

**为什么用 MCP？**

MCP（Model Context Protocol）是 Anthropic 提出的 AI-工具交互标准。本项目的核心创新是 **用 MCP 作为 Agent 和业务数据之间的统一接口**。

```
                     ┌─────────────────┐
Agent: "查GMV"  ──→  │  MCP Server     │  ──→  query_sales_metrics()
Agent: "查库存"  ──→  │  (JSON-RPC 2.0) │  ──→  query_inventory()
Agent: "查竞品"  ──→  │                 │  ──→  query_competitor_prices()
                     └─────────────────┘
```

**6 个 MCP 工具的技术实现**：

```python
# 每个工具 = 名称 + JSON Schema + async 执行函数
MCP_TOOLS = [
    MCPTool("query_sales_metrics", "查GMV/订单量/转化率", {...}),
    MCPTool("query_traffic_data",    "查UV/PV/加购", {...}),
    MCPTool("query_inventory",       "查库存水位", {...}),
    MCPTool("query_competitor_prices","查竞品价格", {...}),
    MCPTool("query_order_detail",    "查订单详情", {...}),
    MCPTool("execute_analytics_query","自定义聚合", {...}),
]
```

**工具调用链路**：
```
Agent 决定调用 tool
  → MCPToolExecutor.execute(tool_name, params)
    → 路由到对应的 async 方法
      → 从 DataGenerator/StreamManager 读取内存数据
        → 返回结构化 JSON
          → Agent 解析 Observation → 生成分析结论
```

### 5.3 Skills 技能库

**Skill 的结构**:

每个 Skill 是一个文件夹，包含三个部分：

```
skills/sales_anomaly/         ← Skill 文件夹名 = Skill ID
  SKILL.md                    ← YAML frontmatter + Markdown 工作流指令
  scripts/detector.py         ← Python 可执行脚本（被 Skill Loader 动态加载）
  resources/                  ← 可选资源文件
```

**SKILL.md 示例结构**:

```markdown
---
name: sales-anomaly-detection
description: 实时检测销售指标异常
triggers:
  - scheduled: every 5 minutes        ← 定时触发
  - manual: user asks about anomaly   ← 手动触发
depends_on:
  - query_sales_metrics               ← 依赖的 MCP 工具
---

# 销售异常检测技能
## 工作流程
1. 获取数据：调用 query_sales_metrics
2. 执行检测：运行 scripts/detector.py（Z-Score + 偏离度）
3. 判定级别：P0(>50%) / P1(30-50%) / P2(15-30%)
4. 生成报告
```

**4 个 Skills 的业务价值**：

| Skill | 解决什么问题 | 输入 | 输出 |
|-------|-------------|------|------|
| `sales-anomaly-detection` | 销售异常没人及时发现 | 实时 GMV/订单量 | 异常级别 + 可能原因 + 建议 |
| `smart-alert` | 告警信息太粗糙、没有分级 | 异常事件 | P0/P1/P2 分级通知 + 推送模板 |
| `competitor-monitor` | 竞品降价了不知道 | 竞品价格流 | 价格对比 + 竞争力分析 + 调价建议 |
| `inventory-optimizer` | 不知道何时补货、补多少 | 库存 + 销量 | 补货量 + 时机 + 安全库存计算 |

### 5.4 Agent 引擎 (`agent/engine.py`)

**Fast 模式的核心流程**（当前运行模式，无需 LLM）：

```
用户输入 "分析今天的销售异常"
  │
  ▼
意图识别（关键词匹配）
  "销售" "异常" → 匹配到 sales-anomaly-detection Skill
  │
  ▼
MCP 工具调用
  query_sales_metrics(time_range="1h")  → 获取真实数据
  │
  ▼
模板引擎生成报告
  ├─ 核心指标概览表（GMV/订单量/客单价）
  ├─ 渠道销售分布（带占比柱状图数据）
  ├─ 异常预警（自动判定 P0/P1/P2）
  ├─ 库存预警（低库存商品列表）
  └─ 行动建议（按优先级排列）
  │
  ▼
返回结构化 AgentResponse
  {answer, steps, skills_used, tools_called, latency_ms}
```

**LLM 模式的流程**（有 API Key 时）：

```
用户输入 → System Prompt + 工具列表 → LLM 规划 → Function Calling
  → 执行 MCP 工具 → 观察结果 → LLM 反思 → 继续调用或生成最终回答
  （最多 5 轮 ReAct 循环）
```

**为什么做双模式？**

| 问题 | Fast 模式 | LLM 模式 |
|------|----------|---------|
| 是否需要 API Key | ❌ 不需要 | ✅ 需要 |
| 响应时间 | < 3 秒 | 5-30 秒 |
| 分析深度 | 基于模板的结构化分析 | 开放式深度推理 |
| 适用场景 | 实时监控、Demo、CI/CD | 复杂根因分析、自然语言交互 |
| API 费用 | ¥0 | 每次 ¥0.01-0.1 |

### 5.5 数据仓库 (`data/warehouse.py`)

**职责**：对内存中的实时数据进行聚合计算。

```
DataGenerator (原始事件流)
  → StreamManager (窗口缓存，最近 200 条)
    → DataWarehouse (聚合查询)
      → Dashboard API (JSON 响应)
```

**核心查询方法**：

| 方法 | 计算内容 | 时间窗口 |
|------|---------|---------|
| `get_overview()` | GMV/订单/UV/转化率/渠道分布/品类分布 | 60 分钟 |
| `get_metrics(time_range)` | GMV 时序数据 + 订单量时序（10分钟桶） | 可配置 |
| `get_anomalies()` | GMV 偏离检测 + 低库存预警 | 5 分钟/60 分钟对比 |
| `get_top_products(limit)` | 按 GMV 排序的 Top N 商品 | 60 分钟 |

### 5.6 前端 Dashboard

**实时大屏的 4 个区域**：

```
┌─────────────────────────────────────────────────────┐
│  [GMV ¥20,792]  [订单 35笔]  [UV 3,309]  [加购 120]│  ← 指标卡片行
├──────────────────────────┬──────────────────────────┤
│  📈 GMV趋势 (ECharts折线)│  📊 渠道占比 (ECharts饼图)│  ← 图表行
│  实时更新10分钟桶聚合     │  各渠道GMV占比可视化      │
├──────────────────────────┬──────────────────────────┤
│  🚨 实时预警列表          │  🔥 热销商品排行          │  ← 底栏
│  P0/P1/P2 自动分级       │  Top 10 GMV 排序         │
└──────────────────────────┴──────────────────────────┘
```

**实时更新机制**：
- 前端每 5 秒轮询 `GET /dashboard/overview`
- 数据引擎持续产生新数据（订单每 2 秒一笔）
- 图表自动重绘（Vue 响应式 + ECharts 增量更新）

---

## 6. 关键数据流

### 6.1 实时监控数据流

```
DataGenerator._generate_orders()  ← asyncio 协程，每 2 秒
  → StreamManager.publish("orders", json_data)
    → SSE 广播到前端（已实现 SSE 通道，前端用轮询）
      → Dashboard 指标卡片更新
        → ECharts 图表增量渲染
```

### 6.2 Agent 分析数据流

```
用户输入 "分析今天GMV为什么下降"
  → POST /api/v1/agent/chat
    → AgentEngine.run(query)
      → intent = detect_intent(query)  # "销售"+"下降" → sales-anomaly
        → MCPToolExecutor.execute("query_sales_metrics", {...})
          → DataGenerator.get_recent_orders(60)  # 拉取近1小时订单
            → 聚合计算 GMV/订单量/渠道分布
              → 返回结构化 JSON
        → _build_fast_answer(query, data, sales)
          → 模板渲染：指标表 + 渠道图 + 异常判定 + 建议
    → AgentResponse {answer, steps, skills_used, latency_ms}
  → 200 OK JSON
```

### 6.3 MCP 工具调用数据流

```
Agent/MCP Client
  → POST /mcp/tools/call {"method":"tools/call","params":{...}}
    → MCPToolExecutor.execute(tool_name, params)
      → _query_sales(params) → DataGenerator.get_recent_orders()
      → 返回 {"gmv": 20792, "order_count": 35, ...}
    → {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"..."}]}}
```

---

## 7. 代码结构

```
ecom-ai-dashboard/
├── README.md                     # 项目说明
├── EXECUTION.md                  # 开发状态跟踪
├── PROJECT_GUIDE.md              # ← 本文件（面试指南）
├── docker-compose.yml            # PG + Redis + Milvus + MinIO
│
├── backend/                      # Python FastAPI (30+ 文件)
│   ├── app/main.py               # FastAPI 入口 + 生命周期管理
│   ├── app/core/
│   │   ├── config.py             # 全局配置（DB/LLM/MCP/数据频率）
│   │   ├── database.py           # SQLAlchemy Async + pgvector
│   │   ├── events.py             # SSE 发布/订阅管理器
│   │   └── security.py           # API Key + JWT 鉴权
│   ├── app/data/                 # ← 数据层（核心）
│   │   ├── generator.py          # 4 条数据流 + 异常注入器
│   │   ├── streams.py            # 流管理器 + SSE 广播
│   │   └── warehouse.py          # 聚合查询引擎
│   ├── app/mcp/                  # ← MCP 协议层
│   │   ├── tools.py              # 6 个 MCP 工具定义 + 执行器
│   │   └── server.py             # JSON-RPC 2.0 HTTP Transport
│   ├── app/agent/                # ← Agent 智能体
│   │   ├── engine.py             # Fast/LLM 双模式引擎
│   │   ├── planner.py            # LLM 任务分解器
│   │   ├── memory.py             # 长期记忆（Milvus 向量库）
│   │   └── skill_loader.py       # Skill 文件系统扫描 + 动态加载
│   ├── app/skills/               # ← 4 个即插即用 Skills
│   │   ├── sales_anomaly/        # SKILL.md + scripts/detector.py
│   │   ├── smart_alert/          # SKILL.md + resources/templates.json
│   │   ├── competitor_monitor/   # SKILL.md + scripts/scraper.py
│   │   └── inventory_optimizer/  # SKILL.md + resources/inventory_model.py
│   ├── app/api/v1/               # REST API 层
│   │   ├── dashboard.py          # 实时数据 API
│   │   ├── agent.py              # Agent 对话 API
│   │   ├── alerts.py             # 预警管理 API
│   │   └── admin.py              # 系统管理 + Skill 热重载
│   └── app/workers/scheduler.py  # 定时 Skill 调度器
│
├── frontend/                     # Vue 3 前端 (15 文件)
│   ├── src/App.vue               # 侧边栏 + 4 页面导航
│   ├── src/pages/
│   │   ├── Dashboard/index.vue   # 实时大屏（指标卡+图表+预警+排行）
│   │   ├── AgentChat/index.vue   # AI 对话面板（SSE + Markdown渲染）
│   │   ├── Alerts/index.vue      # 预警管理（分级筛选+实时刷新）
│   │   └── Settings/index.vue    # Skills 配置 + MCP 工具状态
│   ├── src/components/
│   │   └── MetricCard.vue        # 可复用指标卡片组件
│   ├── src/services/api.js       # 完整 API 封装（4 组接口）
│   └── src/router/index.js       # 前端路由
│
└── demo-data/
    ├── products.json             # 10 个 SKU 商品目录
    └── competitor_baseline.json  # 竞品价格基线数据
```

---

## 8. 技术决策与权衡

### 决策 1：为什么不用 LangChain 的 Agent？

**选择**：自研轻量 Agent 引擎

**原因**：
- LangChain 的 AgentExecutor 抽象层次太多，调试困难（"黑盒"）
- LangChain 的 tool calling 封装过度，出现问题时难以定位是 Prompt 问题还是框架问题
- 本项目 Agent 逻辑清晰（意图识别→工具调用→报告生成），自研只需 ~200 行代码
- LangChain 版本更新频繁，API 不稳定

**代价**：需要自己实现 ReAct 循环和 Tool 编排，但换来的是完全的掌控力。

### 决策 2：为什么用 MCP 而不是直接 REST API？

**选择**：MCP JSON-RPC 2.0 协议

**原因**：
- MCP 是 AI Agent 调用工具的**行业标准**，不是私有协议
- 用了 MCP 后，Agent 可以通过标准接口调用任何工具——无论工具内部是查数据库、调 API、还是跑脚本
- 兼容 Claude Desktop 等 MCP Client，如果未来需要集成第三方 AI 工具，零改动
- JSON-RPC 比 REST 更适合工具调用（统一的 `tools/list` + `tools/call` 端点）

**代价**：多一层协议封装，但带来的是标准化和互操作性。

### 决策 3：Skills 为什么用文件系统而不是数据库？

**选择**：文件系统扫描 + YAML frontmatter

**原因**：
- "文件夹 = Skill" 的直觉模型，开发体验极好
- 天然支持 Git 版本管理——每个 Skill 的修改历史一目了然
- 部署即复制文件夹，不需要数据库 Migration
- YAML frontmatter 是 Claude、Obsidian 等工具的标准格式，LLM 可直接理解

**代价**：不适合需要动态创建 Skill 的 SaaS 场景（但本项目面向企业内部部署）。

### 决策 4：为什么做 LLM/Fast 双模式？

**选择**：根据 API Key 配置自动切换

**原因**：
- 面试 Demo 时不需要现场配 API Key——开箱即用
- Fast 模式不是妥协，它是**另一种有效的 Agent 范式**（基于规则的专家系统）
- 两种模式的接口完全一致（同一个 `AgentEngine.run()`），切换对调用方透明
- 生产环境中，Fast 模式可用于简单查询（省钱），LLM 模式用于复杂分析

### 决策 5：为什么数据用内存而不是 Kafka？

**选择**：asyncio + 内存队列

**原因**：
- MVP 阶段不需要消息队列的持久化和重放能力
- 事件窗口只需最近 200 条（用于计算趋势），超出直接丢弃
- Python asyncio 的协程模型天然适合 I/O 密集型的数据生成
- 降低了部署复杂度（不需要额外 Kafka/Zookeeper 集群）

**未来演进**：当数据量达到每秒万级事件时，替换为 Kafka + Flink 架构，接口不变。

---

## 9. 面试话术

### 9.1 30 秒电梯演讲

> "我做了一个 AI-Native 的电商实时监控平台。核心创新是用 **Agent Skills + MCP 协议**取代了传统看板的'人找数据'模式。Agent 持续监控销售数据流，自主发现异常后自动调用 MCP 工具获取数据，再加载对应的 Skill（比如销售异常检测技能）进行深度分析，最终输出结构化报告和可执行建议。整个流程从数据生成到分析报告，全部自动化，不需要任何人工干预。"

### 9.2 技术亮点叙述（按面试官关注点分类）

**如果面试官关注架构设计**：
> "我设计了一个分层架构。最底层是 asyncio 并发数据引擎，模拟 4 条实时数据流；往上是 MCP 协议层，把 6 个业务查询封装成标准化的 AI 工具；再往上是 Agent 智能体层，包含意图识别、工具调度、报告生成三个模块，以及 4 个即插即用的 Skills；最上面是 Vue 3 + ECharts 的实时大屏。每层之间通过明确的接口解耦，替换任何一层不影响其他层。"

**如果面试官关注 AI/Agent**：
> "Agent 引擎做了双模式设计：Fast 模式基于关键词意图识别 + MCP 工具调用 + 模板引擎，3 秒内出报告；LLM 模式用 Function Calling 做 ReAct 推理，能做更深度的根因分析。两种模式通过 `has_real_llm()` 自动切换，接口完全一致。Skills 的设计借鉴了 Anthropic 的 Agent Skills 规范——每个 Skill 是文件夹，包含 SKILL.md 工作流定义和可执行脚本，Loader 通过 importlib 动态加载，做到了真正的即插即用。"

**如果面试官关注 MCP 协议**：
> "我用了 MCP JSON-RPC 2.0 协议作为 Agent 和业务工具的交互标准。相比直接调 REST API，MCP 有三个优势：一是标准化的工具发现机制（`tools/list`），Agent 不需要硬编码工具列表；二是统一的调用接口（`tools/call`），所有工具用同一个端点；三是兼容 Claude Desktop 等 MCP Client，未来可以零改动接入第三方 AI。我在项目里定义了 6 个 MCP 工具，覆盖销售、流量、库存、竞品、订单和分析查询。"

**如果面试官关注实时数据**：
> "数据引擎用 asyncio 协程池跑了 5 个并发任务：订单流每 2 秒产生一笔，流量流每 10 秒更新，库存流每 30 秒，竞品流每 5 分钟，还有一个异常控制器随机注入异常来测试检测能力。数据通过 StreamManager 做窗口缓存（最近 200 条），然后 DataWarehouse 做聚合计算。整个数据链路从生成到前端展示延迟小于 1 秒。"

### 9.3 项目亮点一句话总结

1. **Agent Skills 即插即用架构** — 新增一个分析能力 = 复制一个文件夹
2. **MCP 标准化工具接口** — 6 个工具统一协议，兼容任何 MCP Client
3. **LLM/Fast 双模式** — 有 Key 用 AI 推理，没 Key 也能用专家系统
4. **实时数据引擎** — asyncio 5 协程并发，毫秒级数据生成到展示
5. **端到端自动化** — 从数据监控到异常发现到分析报告，全链路 AI 驱动

---

## 10. 高频追问与应答

### Q1: "MCP 协议和 Function Calling 有什么区别？"

**答**：两者是不同层次的概念。Function Calling 是 LLM 的**能力**——让模型输出结构化的函数调用请求。MCP 是工具提供方的**协议标准**——规定工具如何被发现、描述和调用。实际工作中它们是互补的：

```
LLM(Function Calling) → 输出: {tool: "query_sales", params: {...}}
  ↓
MCP Server → 接收 JSON-RPC → 执行 → 返回标准格式
  ↓
LLM → 解析 Observation → 生成回答
```

Function Calling 是"大脑怎么发出指令"，MCP 是"手脚怎么执行指令"。

### Q2: "Fast 模式怎么保证分析质量？没有 LLM 不会很死板吗？"

**答**：Fast 模式的质量保障来自三个方面：
1. **数据是真实的** — MCP 工具返回的是实时数据，不是编造的
2. **分析逻辑是专家经验编码的** — Z-Score 异常判定、安全库存公式都是经过验证的算法
3. **模板是精心设计的** — 指标表 + 渠道图 + 预警分级 + 行动建议，覆盖了 80% 的常见分析场景

Fast 模式适合**监控类**场景（今天有没有异常？哪个渠道出问题了？）。LLM 模式适合**探索类**场景（为什么会持续下降？跟竞品策略有什么关系？），两者互补而非替代。

### Q3: "如果数据量变大（每秒万级订单），架构需要怎么改？"

**答**：关键是**接口不变，底层替换**：
1. `DataGenerator` → 替换为 Kafka Consumer（消费真实订单流）
2. `StreamManager` 的内存窗口 → 替换为 Flink 滑动窗口
3. `DataWarehouse` 的遍历计算 → 替换为 ClickHouse/StarRocks 预聚合查询
4. MCP 工具执行器 → 改为查询 ClickHouse 而非遍历内存列表

整个 MCP 层、Agent 层、API 层、前端层的接口都不需要改——这就是分层架构的价值。

### Q4: "Skills 和 MCP 工具有什么关系？为什么分两层？"

**答**：Skills 和 MCP 工具是**不同抽象层次**的概念：
- MCP 工具是**原子操作**：查一个数、执行一个查询。像"螺丝刀"。
- Skill 是**完整工作流**：理解问题→选工具→调工具→分析结果→生成报告。像"维修手册"。

一个 Skill 通常会调用多个 MCP 工具。比如 `sales-anomaly-detection` Skill 会调用 `query_sales_metrics` + `execute_analytics_query`。
分层的好处是：工具可以被多个 Skill 复用，Skill 可以独立升级而不影响工具层。

### Q5: "这个项目跟普通的 BI 看板（如 Grafana、Metabase）有什么区别？"

**答**：核心区别是**主动性**：
- BI 看板：数据可视化 + 阈值告警。你设置"GMV 下降 20% 就发邮件"，但它不会告诉你**为什么**下降。
- 本项目：Agent 发现异常后**主动分析原因**。它不只是告诉你"GMV 降了 30%"，还会告诉你"淘宝渠道正常，京东渠道降了 60%，同时发现竞品 A 在京东做了大促降价"——这是 BI 看板做不到的。

另外，BI 看板的交互方式是"人写 SQL/拖拽图表"，本项目的交互方式是"用自然语言描述问题"。

---

## 附录：快速启动命令

```bash
# 后端
cd backend && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# 前端
cd frontend && npm install && npm run dev

# 测试 Agent
curl -X POST http://localhost:8001/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"分析今天的销售异常"}'

# 查看 MCP 工具列表
curl -X POST http://localhost:8001/mcp/tools/list \
  -H "Content-Type: application/json"

# API 文档
open http://localhost:8001/docs
```

---

> 📅 文档版本: 1.0 | 🎯 适用岗位: AI 大模型应用开发 / Agent 工程师 / RAG 工程师 / LLM 应用全栈
