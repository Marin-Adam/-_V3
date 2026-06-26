# 电商智能决策看板平台 — 技术栈与功能对照

> 每个技术在本项目中承担的具体角色。标注 ✅ 的为实际在用，📋 的为规划中。
> **最后更新**: 2026-06-18（经 import 逐行核查）

---

## 一、后端核心 (Python 3.12+)

### Web 框架

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **FastAPI** | 0.111+ | ✅ | ASGI Web 框架，定义全部 REST API 端点（dashboard/agent/alerts/admin 共 12 个接口），提供自动 OpenAPI 文档、依赖注入、请求验证 |
| **Uvicorn** | 0.29+ | ✅ | ASGI 服务器，启动 FastAPI 应用（运行时依赖，非代码 import） |
| **Pydantic Settings** | 2.2+ | ✅ | 从 `.env` 文件加载 40+ 配置项（数据库/LLM/MCP/数据生成频率等），提供类型校验和单例缓存 |
| **SSE-Starlette** | 1.8+ | ✅ | 提供 `EventSourceResponse`，实现 Agent 对话的 SSE 流式输出 |
| **HTTPX** | 0.27+ | ✅ | OpenAI SDK 底层异步 HTTP 客户端（间接依赖） |

### 数据库与存储

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **SQLAlchemy 2.0 Async** | 2.0+ | ✅ | 异步 ORM 框架，定义 `AlertRecord`、`SkillExecution`、`DashboardSnapshot` 三张业务表，使用 `Mapped` 类型注解 |
| **asyncpg** | 0.29+ | ✅ | PostgreSQL 异步驱动，SQLAlchemy 的底层通信引擎（间接依赖） |
| **pgvector** | 0.2+ | 📋 | PostgreSQL 向量扩展。docker-compose 中已配置镜像，代码中尚未启用 |

### 向量数据库

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **Milvus** | 2.3 | 📋 | 向量数据库。docker-compose 已部署，`agent/memory.py` 有连接桩代码，但 `_store_milvus()` / `_search_milvus()` 实际回退到内存列表 |
| **PyMilvus** | 2.3+ | ✅ | Milvus Python SDK。已 import，连接逻辑在 `AgentMemory.__init__` 中尝试连接 |

### AI / Agent / LLM

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **OpenAI SDK** | 1.30+ | ✅ | 统一的 LLM 调用接口。Agent 引擎通过 `AsyncOpenAI` + `base_url` 覆盖，同时兼容 Qwen(DashScope)、OpenAI、DeepSeek 三种后端 |
| **Qwen (通义千问)** | — | ✅ | 通过 OpenAI 兼容端点 (`https://dashscope.aliyuncs.com/compatible-mode/v1`) 调用 `qwen-plus` 模型。代码中用 OpenAI SDK 访问，不依赖 DashScope SDK |

### 协议与工具标准

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **MCP 协议** | JSON-RPC 2.0 | ✅ | 自建实现（`mcp/server.py` + `mcp/tools.py`）。将 6 个业务查询封装为标准 AI 工具，定义 `tools/list` 和 `tools/call` 两个 JSON-RPC 端点。未使用官方 `mcp` Python SDK |
| **Agent Skills** | 自研规范 | ✅ | 基于 YAML frontmatter + Markdown 工作流 + Python 脚本的技能包格式。Skills 文件夹通过文件系统扫描发现，`importlib` 动态加载脚本 |

### 数据处理

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **PyYAML** | 6.0+ | ✅ | `SkillLoader` 用 `yaml.safe_load()` 解析 `SKILL.md` 文件头的 YAML frontmatter |
| **NumPy** | — | 📋 | 规划用于异常检测中的方差/标准差计算。当前 `detector.py` 使用标准库 `math` 替代 |

### 安全与认证

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **python-jose** | 3.3+ | ✅ | JWT 库。`security.py` 中 `create_access_token()` 生成 HS256 签名令牌。当前认证为桩代码（`get_current_tenant_id` 返回 `"default-tenant"`） |

### 实时数据引擎

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **asyncio** | Python 3.12 内置 | ✅ | 异步 I/O 框架。`DataGenerator` 创建 5 个并发 `asyncio.Task`；`SSEManager` 用 `asyncio.Queue` 实现频道订阅/发布 |
| **Loguru** | 0.7+ | ✅ | 结构化日志库。全后端统一使用，记录服务启停、Agent 推理步骤、异常注入事件 |

---

## 二、前端 (Vue 3 + Vite)

### 核心框架

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **Vue 3** | 3.4+ | ✅ | Composition API + `<script setup>` 语法 |
| **Vue Router 4** | 4.3+ | ✅ | `createWebHistory` 模式定义 4 条路由，全部懒加载 |
| **Pinia** | 2.1+ | ✅ | 全局注册为插件，当前尚未创建任何 store（`main.js` 中仅 `app.use(createPinia())`） |
| **Vite 5** | 5.2+ | ✅ | 构建工具/开发服务器，代理 `/api` 和 `/mcp` 到后端 8001 端口 |

### UI 组件库

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **Element Plus** | 2.7+ | ✅ | 布局系统、侧边栏导航、卡片、表格、标签、按钮等 30+ 组件。当前全局注册（非按需引入） |
| **@element-plus/icons-vue** | 2.3+ | ✅ | 侧边栏 4 个图标 |

### 数据可视化

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **ECharts 5** | 5.5+ | ✅ | Dashboard 按需引入：`LineChart` + `PieChart` + Tooltip/Legend/Grid |
| **vue-echarts** | 6.7+ | ✅ | ECharts 的 Vue 3 封装组件 |

### HTTP 与 Markdown

| 技术 | 版本 | 状态 | 在本项目中的功能 |
|------|------|------|-----------------|
| **Axios** | 1.7+ | ✅ | 封装 4 组 API 模块（dashboardAPI/agentAPI/alertsAPI/adminAPI） |
| **Marked** | 12.0+ | ✅ | AgentChat 页面用 `marked.parse()` 渲染 Markdown 分析报告为富文本 |

---

## 三、基础设施 (Docker Compose)

| 技术 | 镜像 | 状态 | 用途 |
|------|------|------|------|
| **PostgreSQL 16 + pgvector** | `pgvector/pgvector:pg16` | ✅ | 主数据库（代码中 `init_db()` 创建空表，业务数据存储在内存中） |
| **Redis 7** | `redis:7-alpine` | 📋 | 已部署但代码中未连接 redis 客户端。仅 `config.py` 中有 `REDIS_URL` 配置项 |
| **Milvus** | `milvusdb/milvus:v2.3.4` | 📋 | 已部署但集成代码为桩。`memory.py` 回退到内存列表 |
| **etcd** | `quay.io/coreos/etcd:v3.5.5` | ✅ | Milvus 元数据后端 |
| **MinIO** | `minio/minio:latest` | ✅ | Milvus 对象存储后端 |

---

## 四、技术栈全景图

```
                    前端展示层
    ┌──────────────────────────────────────┐
    │  Vue 3 · Element Plus · ECharts 5    │
    │  Pinia · Vue Router 4 · Marked       │
    │  Axios · Vite 5 · vue-echarts        │
    └──────────────────┬───────────────────┘
                       │ SSE / REST
    ┌──────────────────▼───────────────────┐
    │             FastAPI 网关              │
    │  FastAPI · Uvicorn · Pydantic · JWT  │
    └──────────────────┬───────────────────┘
                       │
    ┌──────────────────▼───────────────────┐
    │          Agent 智能体引擎             │
    │  OpenAI SDK · 自建 MCP 协议           │
    │  Agent Skills · Skill Loader         │
    │  PyYAML · Loguru · asyncio           │
    └──────────────────┬───────────────────┘
                       │
    ┌──────────────────▼───────────────────┐
    │          数据与存储层                 │
    │  SQLAlchemy · asyncpg                │
    │  PyMilvus (📋 桩代码)                │
    │  asyncio (实时数据引擎)              │
    └──────────────────┬───────────────────┘
                       │
    ┌──────────────────▼───────────────────┐
    │      Docker Compose 基础设施         │
    │  PostgreSQL 16 · Redis 7 (📋)        │
    │  Milvus · etcd · MinIO              │
    └──────────────────────────────────────┘

    ✅ = 实际在用    📋 = 已部署但代码未对接 / 桩代码
```

---

## 五、已移除的依赖（2026-06-18 清理）

以下 15 个包从 `requirements.txt` 中移除，原因均为 **代码中无任何 import 引用**：

| 包名 | 移除原因 |
|------|---------|
| `langgraph` | Agent 引擎为纯自建 ReAct 循环，未使用 LangGraph StateGraph |
| `langchain` | 无任何 import |
| `langchain-openai` | 无任何 import（直接用 openai SDK） |
| `dashscope` | 通过 OpenAI SDK 的 base_url 覆盖访问 Qwen，不需要 DashScope SDK |
| `numpy` | `detector.py` 使用标准库 `math`，未 import numpy |
| `pandas` | 无任何 import |
| `alembic` | 无 `migrations/` 目录，无 `alembic.ini` |
| `aiosqlite` | 项目使用 PostgreSQL，不使用 SQLite |
| `redis` | `config.py` 中有 URL 配置但代码中无 redis 客户端连接 |
| `pgvector` | docker-compose 镜像包含但代码中无 import |
| `passlib` | 认证功能未实现，`security.py` 中无 import |
| `python-multipart` | 无表单上传功能 |
| `pytest` / `pytest-asyncio` / `pytest-cov` | 无 `tests/` 目录 |
