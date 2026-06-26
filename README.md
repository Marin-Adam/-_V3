# AI-Native 电商实时监控智能决策平台 V3.0

**多智能体 A2A 协作 + MCP 可插拔工具链 + 流式实时分析**

将 AI 从"被动查询"升级为"主动思考、自主分析、多 Agent 协作"的智能决策核心。

## 🚀 一键部署

```bash
# Linux / macOS / Git Bash
bash deploy.sh setup    # 首次运行：安装依赖
bash deploy.sh start    # 启动全部 6 个服务
bash deploy.sh status   # 查看运行状态
bash deploy.sh stop     # 停止全部服务
```

```powershell
# Windows PowerShell
.\deploy.ps1 setup      # 首次运行：安装依赖
.\deploy.ps1 start      # 启动全部 6 个服务
.\deploy.ps1 status     # 查看运行状态
.\deploy.ps1 stop       # 停止全部服务
```

启动后打开 **http://localhost:5173**

## 🏗️ V3.0 架构

```
┌──────────────────────────────────────────────────────────────┐
│                Vue 3 + ECharts 展示层                        │
│  Dashboard │ AI对话 │ 营销洞察🆕 │ 预警中心 │ Skills配置    │
└──────────────────────────┬───────────────────────────────────┘
                           │ REST / SSE
┌──────────────────────────▼───────────────────────────────────┐
│         主 Agent (Orchestrator)  :8001                       │
│         任务拆解 → A2A 调度 → 流式输出                       │
└──────┬──────────┬──────────┬──────────┬──────────────────────┘
       │A2A HTTP  │A2A HTTP  │A2A HTTP  │A2A HTTP
┌──────▼───┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐
│DataAgent │ │Analyze  │ │Sentiment│ │ Report  │
│  :8010   │ │ :8011   │ │ :8012   │ │ :8013   │
│ 数据查询 │ │ 统计分析│ │ 情感评分│ │ 报告生成│
└──────────┘ └─────────┘ └─────────┘ └─────────┘
       │                                       │
┌──────▼───────────────────────────────────────▼──────────────┐
│         MCP 可插拔工具层 (11 工具, 7 分类)                   │
│  sales │ traffic │ inventory │ competitor │ analytics │ ad  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│     数据引擎 (DataGenerator / Kafka / DB polling)            │
│     CacheManager (L1本地 + L2 Redis + 失效广播)              │
└──────────────────────────────────────────────────────────────┘
```

## 📦 服务清单

| 服务 | 端口 | 功能 |
|------|------|------|
| 主后端 (FastAPI) | 8001 | API + Orchestrator + MCP + Skills |
| DataAgent | 8010 | 数据格式化/校验 |
| AnalyzeAgent | 8011 | 统计分析/异常检测/复购率 |
| SentimentAgent | 8012 | 情感评分/关键词提取 |
| ReportAgent | 8013 | 综合报告生成 |
| 前端 (Vue 3) | 5173 | 实时大屏 + AI对话 + 营销洞察 |

## 🧪 API 端点

### Multi-Agent Orchestration (V3.0 核心)

```bash
# 流式 — 逐步展示每个 Agent 分析过程
curl -N -X POST http://localhost:8001/api/v1/agent/orchestrate/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"分析京东渠道GMV为什么下降"}'

# 非流式 — 返回完整 JSON + Markdown 报告
curl -X POST http://localhost:8001/api/v1/agent/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"query":"analyze sales anomaly"}'

# Agent 在线状态
curl http://localhost:8001/api/v1/agent/agents/status
```

### Insights (营销洞察)

```bash
curl http://localhost:8001/api/v1/insights/overview
curl http://localhost:8001/api/v1/insights/categories
curl http://localhost:8001/api/v1/insights/repurchase
curl http://localhost:8001/api/v1/insights/sentiment
```

### MCP Tools (11 工具, 运行时管理)

```bash
curl -X POST http://localhost:8001/mcp/tools/list
curl http://localhost:8001/mcp/admin/tools
curl -X POST "http://localhost:8001/mcp/admin/status?tool=query_sales_metrics&enabled=false"
```

## 📂 项目结构

```
ecom-ai-dashboard/
├── deploy.sh                  # Linux/Mac 一键部署
├── deploy.ps1                 # Windows 一键部署
├── docker-compose.yml         # Docker 基础设施
├── backend/                   # FastAPI 后端
│   └── app/
│       ├── agent/             # Agent 引擎
│       │   ├── orchestrator.py    # 🆕 主Agent A2A调度器
│       │   ├── sub_agents.py      # 🆕 4个子Agent实现
│       │   ├── a2a_client.py      # 🆕 A2A HTTP客户端
│       │   └── engine.py          # 经典3层LLM引擎
│       ├── mcp/               # MCP协议层
│       │   ├── registry.py        # 🆕 注册表模式
│       │   ├── server.py          # 🆕 含admin端点
│       │   └── tools/             # 🆕 11个独立工具文件
│       ├── services/
│       │   └── cache_manager.py   # 🆕 L1/L2缓存
│       ├── api/v1/
│       │   └── insights.py        # 🆕 营销洞察API
│       └── data/                  # 数据引擎
├── microservices/             # 🆕 A2A微服务
│   ├── data-agent/            # :8010
│   ├── analyze-agent/         # :8011
│   ├── sentiment-agent/       # :8012
│   └── report-agent/          # :8013
├── scripts/                   # 🆕 离线任务
│   ├── milvus_embedding_job.py
│   └── preaggregation_job.py
└── frontend/                  # Vue 3 前端
    └── src/pages/
        └── Insights/          # 🆕 营销洞察页
```

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| AI Agent | 自研 A2A 多智能体 + 3层LLM降级 |
| MCP 协议 | 注册表模式 + JSON-RPC 2.0 + 热插拔 |
| Agent Skills | 文件系统扫描 + YAML + 动态加载 (4个) |
| 后端 | FastAPI + asyncio + SSE 流式 |
| 缓存 | L1进程内存 + L2 Redis + Pub/Sub失效广播 |
| 安全护栏 | Guardrails 阈值拦截 + 人工审批 |
| 前端 | Vue 3 + ECharts 5 + Element Plus + Vite |
| 数据库 | PostgreSQL + pgvector (可选，DataGenerator降级) |
| LLM | Qwen / DeepSeek / GPT-4o (可选，Fast模式降级) |

## 📄 License

MIT
