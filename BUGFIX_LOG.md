# Bug 修复日志 — ecom-ai-dashboard

> **修复日期**: 2026-06-18  
> **修复人**: AI Assistant  
> **总修复数**: 8 bugs + 1 结构性改进

---

## 🔴 阻断级 Bug (P0)

### Bug #1: `warehouse.py:125` — `_getattr__` 拼写错误导致运行时崩溃

**文件**: `backend/app/data/warehouse.py`  
**严重级别**: P0 — 必定触发 AttributeError  
**发现日期**: 2026-06-18

**问题描述**:
`get_anomalies()` 方法中低库存检测代码：
```python
product_names = {p["id"]: p["name"] for p in self._gen._getattr__("PRODUCTS") or []}
```
- `_getattr__` 是拼写错误，应为 `getattr`
- `DataGenerator` 类并没有 `_PRODUCTS` 属性（产品列表在 `generator.py` 模块级 `PRODUCTS` 变量中）
- `product_names` 构建后被赋值但从未使用——死代码
- 当有任何商品库存 < 20 时，此代码路径必定抛出 `AttributeError`

**修复方案**:
1. 将 `product_names` 构建移到循环外部，使用同文件中已存在的模块级 `_PRODUCTS_CACHE`
2. 在异常描述中使用 `product_names.get(pid, pid)` 包含产品名称，提高可读性

**修复前**:
```python
for pid, qty in self._gen.inventory.items():
    if qty < 20:
        product_names = {p["id"]: p["name"] for p in self._gen._getattr__("PRODUCTS") or []}
        anomalies.append({
            "type": "low_stock",
            "description": f"库存预警: {pid} 仅剩 {qty} 件",
            ...
        })
```

**修复后**:
```python
product_names = {p["id"]: p["name"] for p in _PRODUCTS_CACHE}
for pid, qty in self._gen.inventory.items():
    if qty < 20:
        pname = product_names.get(pid, pid)
        anomalies.append({
            "type": "low_stock",
            "description": f"库存预警: {pname} ({pid}) 仅剩 {qty} 件",
            ...
        })
```

---

### Bug #2: `agent.py` — SSE 流式响应根本不会发送事件

**文件**: `backend/app/api/v1/agent.py`  
**严重级别**: P0 — 流式端点完全不工作  
**发现日期**: 2026-06-18

**问题描述**:
`agent_chat_stream()` 中 `event_generator()` 的执行顺序完全反了：
```python
async def event_generator():
    async for sse_event in sse_manager.subscribe(channel):  # ① 先订阅
        yield sse_event
    await engine.run_stream(request.query, channel)          # ② 再执行引擎
```
- `subscribe()` 是一个异步生成器，它会一直阻塞等待事件
- `engine.run_stream()` 在 `subscribe()` **退出后**才被调用
- 但 `subscribe()` 只有在收到 `None` 哨兵值（由 `close_channel()` 发送）时才会退出
- `close_channel()` 是在 `run_stream()` 内部的 `finally` 块调用的
- 结果：**死锁** — `subscribe` 等待 `run_stream` 发送事件，但 `run_stream` 永远不执行

**修复方案**:
用 `asyncio.create_task` 将 `engine.run_stream()` 作为后台任务启动，然后再订阅事件。这样引擎在后台发布事件，订阅者在前台消费。

**修复后**:
```python
async def event_generator():
    engine_task = asyncio.create_task(engine.run_stream(request.query, channel))
    try:
        async for sse_event in sse_manager.subscribe(channel):
            yield sse_event
    finally:
        await engine_task  # 确保引擎完成
```

**附加修改**: 文件顶部增加 `import asyncio`。

---

## 🟡 逻辑错误 (P1)

### Bug #3: `warehouse.py` — 转化率计算时间窗口不一致

**文件**: `backend/app/data/warehouse.py`  
**严重级别**: P1 — 计算结果无意义  
**发现日期**: 2026-06-18

**问题描述**:
`get_overview()` 中转化率计算公式为：
```python
order_count = len(recent_orders)   # 最近 60 分钟的订单数
total_uv = sum(t["uv"] for t in traffic.values())  # 全量累计 UV（从启动到现在的总和）
conversion = round(order_count / total_uv * 100, 2)
```
- 分子是 60 分钟窗口，分母是全量累计值
- 随着系统运行时间增长，分母越来越大，转化率趋近于 0%
- 完全失去业务参考意义

**修复方案**:
利用 `StreamManager` 的 traffic 窗口数据，按 product_id 分组计算每个产品在窗口期内的 UV 增量（latest - earliest），然后求和得到近似 60 分钟 UV。如果窗口数据不足则回退到累计 UV。

**修复后**:
```python
if self._streams:
    traffic_window = self._streams.get_window("traffic", limit=1000)
    if len(traffic_window) >= 2:
        product_uv_range: dict[str, dict[str, int]] = {}
        for event in traffic_window:
            pid = event.get("product_id") if isinstance(event, dict) else None
            uv = event.get("uv", 0) if isinstance(event, dict) else 0
            if pid:
                if pid not in product_uv_range:
                    product_uv_range[pid] = {"first": uv, "last": uv}
                else:
                    product_uv_range[pid]["last"] = uv
        total_uv = sum(max(0, v["last"] - v["first"]) for v in product_uv_range.values())
        if total_uv == 0:
            total_uv = total_cumulative_uv
    else:
        total_uv = total_cumulative_uv
else:
    total_uv = total_cumulative_uv
```

---

## 🟡 资源泄漏 (P1)

### Bug #4: Alerts 页面 — 定时器未清理导致内存泄漏

**文件**: `frontend/src/pages/Alerts/index.vue`  
**严重级别**: P1 — SPA 页面切换后定时器继续运行  
**发现日期**: 2026-06-18

**问题描述**:
`onMounted` 中创建的 `setInterval` 在组件卸载时没有被清除：
```javascript
onMounted(() => { fetch(); timer = setInterval(fetch, 10000) })
// 缺少 onUnmounted 清理
```
用户每次离开 Alerts 页面再回来会创建新的定时器，旧的定时器永远不释放。

**修复方案**:
添加 `onUnmounted` 钩子清除定时器。

**修复后**:
```javascript
import { ref, onMounted, onUnmounted, watch } from 'vue'
// ...
onMounted(() => { fetch(); timer = setInterval(fetch, 10000) })
onUnmounted(() => { if (timer) { clearInterval(timer); timer = null } })
```

---

## 🟡 代码重复与风格问题 (P2)

### Bug #5: `CST` 和 `now_cst()` 在三处重复定义

**文件**: `backend/app/data/generator.py`, `backend/app/data/warehouse.py`, `backend/app/agent/engine.py`  
**严重级别**: P2 — 代码重复，修改时容易遗漏  
**发现日期**: 2026-06-18

**修复方案**:
新建 `backend/app/core/constants.py` 作为唯一来源，三个文件统一引用。

**新增文件**:
```python
# backend/app/core/constants.py
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

def now_cst() -> datetime:
    return datetime.now(CST)
```

**涉及修改**:
- `generator.py`: 删除 `CST`/`now_cst()` 定义，改为 `from app.core.constants import CST, now_cst`
- `warehouse.py`: 同上 + 删除重复的 `from datetime import ...` 和 `from typing import Optional` 行内导入
- `engine.py`: 删除 `CST = timezone(timedelta(hours=8))`，改为 `from app.core.constants import CST` + 移除不再需要的 `from datetime import timezone, timedelta`

---

### Bug #6a: `generator.py` — 行内 import 位置异常

**文件**: `backend/app/data/generator.py`  
**严重级别**: P2 — 代码可读性  
**发现日期**: 2026-06-18

**问题描述**:
`from typing import Optional` 出现在函数定义之后、第三方库导入之前（第 22 行），违反 PEP 8 导入顺序规范。

**修复方案**:
将 `from typing import Optional` 移到文件顶部与其他标准库导入合并。

---

### Bug #6b: `DataWarehouse.__init__` — 类型注解不精确

**文件**: `backend/app/data/warehouse.py`  
**严重级别**: P2  
**发现日期**: 2026-06-18

**问题描述**:
`request` 参数默认为 `None` 但类型标注为 `Request`（非 Optional）：
```python
def __init__(self, request: Request = None):
```

**修复方案**:
```python
def __init__(self, request: Optional[Request] = None):
```

---

## 🟡 封装破坏 (P2)

### Bug #7: `scheduler.py` 和 `engine.py` — 直接调用 MCP 私有方法

**文件**: `backend/app/workers/scheduler.py`, `backend/app/agent/engine.py`  
**严重级别**: P2 — 违反封装原则  
**发现日期**: 2026-06-18

**问题描述**:
`SkillScheduler` 和 `AgentEngine._run_fast()` 直接调用 `MCPToolExecutor` 的 `_` 前缀私有方法：
- `self.mcp._query_sales(...)`
- `self.mcp._query_traffic(...)`
- `self.mcp._query_inventory(...)`
- `self.mcp._query_competitor(...)`
- `self.mcp._execute_analytics(...)`

这些方法签名如果变更，调用方会静默出错。

**修复方案**:
全部改为通过公共接口 `self.mcp.execute(tool_name, params)` 调用。

**scheduler.py 修复**:
```python
# Before
sales_data = await self.mcp._query_sales({"time_range": "1h"})
competitor_data = await self.mcp._query_competitor({})
inventory = await self.mcp._query_inventory({"alert_only": True})
# After
sales_data = await self.mcp.execute("query_sales_metrics", {"time_range": "1h"})
competitor_data = await self.mcp.execute("query_competitor_prices", {})
inventory = await self.mcp.execute("query_inventory", {"alert_only": True})
```

**engine.py 修复**:
`_run_fast()` 中的 5 处私有方法调用全部改为 `self.mcp.execute("tool_name", params)`。

---

### Bug #8: `planner.py` — LLM 可能幻觉出不存在的工具名

**文件**: `backend/app/agent/planner.py`  
**严重级别**: P2 — 可能导致下游 Agent 执行失败  
**发现日期**: 2026-06-18

**问题描述**:
`TaskPlanner.plan()` 直接使用 LLM 返回的 `tool_or_skill` 字段构建 `SubTask`，不验证该工具/技能是否真实存在。LLM 可能返回 hallucinated 的名称。

**修复方案**:
解析 LLM 输出后，检查每个子任务的 `tool_or_skill` 是否在 `available_tools` ∪ `available_skills` 中。对于不在列表中的名称，使用关键词匹配回退到最接近的真实工具（sales/traffic/inventory/competitor/anomaly），无法匹配则使用安全的默认值 `query_sales_metrics`。

**修复后核心逻辑**:
```python
valid_names = set(available_tools) | set(available_skills)
for st in data.get("sub_tasks", []):
    tool_or_skill = st.get("tool_or_skill", "")
    if tool_or_skill not in valid_names:
        # Keyword-based fallback
        if "sales" in tool_or_skill.lower() or "query" in tool_or_skill.lower():
            tool_or_skill = "query_sales_metrics"
        elif "traffic" in tool_or_skill.lower():
            tool_or_skill = "query_traffic_data"
        # ... more fallbacks
        else:
            tool_or_skill = "query_sales_metrics"  # Safe default
        st["tool_or_skill"] = tool_or_skill
```

---

## 📊 修复统计

| 严重级别 | 数量 | Bug 编号 |
|---------|------|----------|
| P0 阻断 | 2 | #1, #2 |
| P1 逻辑/泄漏 | 2 | #3, #4 |
| P2 代码质量 | 5 | #5, #6a, #6b, #7, #8 |

| 改动类型 | 文件数 | 涉及文件 |
|---------|--------|---------|
| 新增文件 | 1 | `backend/app/core/constants.py` |
| 修改文件 | 7 | `generator.py`, `warehouse.py`, `engine.py`, `agent.py`, `scheduler.py`, `planner.py`, `Alerts/index.vue` |

---

## 🔴 回归修复：常量提取引入的 P0 回归 (Bug #10)

> **发现日期**: 2026-06-18（第二轮代码审查时发现）  
> **严重级别**: P0 — 运行时静默失败

### Bug #10: `generator.py` — `_parse_ts()` 因缺少 `datetime` 导入而静默失败

**文件**: `backend/app/data/generator.py`  
**引入原因**: Bug #5 修复时将 `from datetime import datetime, timezone, timedelta` 替换为 `from app.core.constants import CST, now_cst`，但遗漏了 `datetime` 类本身仍被 `_parse_ts()` 使用。

**影响链路**:
```
_parse_ts() → NameError: name 'datetime' is not defined
  → except Exception: return 0  (静默吞掉)
    → get_recent_orders() 中 cutoff 计算 = now_cst().timestamp() - minutes * 60
    → 所有订单都满足 _parse_ts(order["timestamp"]) > 0
    → 时间过滤完全失效，get_recent_orders() 永远返回全量数据
```

**修复**: 添加 `from datetime import datetime`（保留 `CST` 和 `now_cst` 从 constants 导入）。

**同时清理的死导入**（本轮审查发现，均来自原始代码）:
- `engine.py`: 移除 `import re`（从未使用）
- `planner.py`: 移除 `from typing import Optional`（参数类型注解未使用 Optional 包装）
- `generator.py`: 移除 `from typing import Optional`（同样从未使用）

---

## ⚠️ 已知尚未修复的问题

以下问题超出本次 Bug 修复范围，需要更大规模的重构：

1. **`security.py` — 认证是纯桩代码** (需完整的多租户认证方案)
2. **`memory.py` — Milvus 集成是空壳** (需实现 embedding 生成 + 真实的 Milvus 读写)
3. **`scheduler.py` — 硬编码占位参数** (`classify_anomaly(0.05, 1.2)` 未使用实际获取的 sales_data)
4. **Dashboard 页面 — 5 秒轮询改为 SSE 推送** (架构升级)

---

---

## 🧹 补充清理：虚假依赖移除 (Bug #9)

> **修复日期**: 2026-06-18  
> **严重级别**: P2 — 文档与代码不一致，误导开发者

### Bug #9: `requirements.txt` 和 `TECH_STACK.md` 包含大量未使用的依赖

**文件**: `backend/requirements.txt`, `TECH_STACK.md`  
**发现日期**: 2026-06-18

**问题描述**:
通过逐行扫描 `backend/app/` 下所有 `*.py` 文件的 import 语句，发现 `requirements.txt` 中 **15 个包从未被任何代码引用**：

| 包 | TECH_STACK.md 声称的用途 | 实际情况 |
|----|--------------------------|---------|
| `langgraph` | "Agent 多步骤状态管理核心" | 引擎为纯自建 ReAct，无任何 import |
| `langchain` | "Prompt 模板、Chain 抽象" | 无任何 import |
| `langchain-openai` | "LangChain 与 OpenAI 桥接" | 无任何 import（直接用 OpenAI SDK） |
| `dashscope` | "阿里云灵积模型服务 SDK" | 代码通过 OpenAI SDK + base_url 覆盖访问 Qwen |
| `numpy` | "异常检测中 np.var()、np.std()" | `detector.py` 用标准库 `math.sqrt()` |
| `pandas` | "复杂数据聚合预留" | 无任何 import |
| `alembic` | "数据库迁移工具" | 无 `migrations/` 目录，无 `alembic.ini` |
| `redis` | "消息队列、Celery broker" |仅 `config.py` 中有 URL 字符串，无 redis 客户端 import |
| `pgvector` | "向量扩展" | docker-compose 配置了镜像，代码中无 import |
| `aiosqlite` | 未在 TECH_STACK 中提及 | 项目用 PostgreSQL，从未配置 SQLite |
| `passlib` | "密码哈希库" | `security.py` 中无 import |
| `python-multipart` | 未提及 | 无文件上传功能 |
| `pytest / pytest-asyncio / pytest-cov` | "测试框架" | 无 `tests/` 目录 |

**修复方案**:
1. `requirements.txt` 从 27 行精简为 12 行（仅保留实际 import 或间接依赖的包）
2. `TECH_STACK.md` 重写：每项标注 ✅（在用）/ 📋（规划中），移除不实声明
3. 全景图更新：移除未使用的 LangChain/LangGraph/numpy/Pandas 等

**保留的 12 个依赖**（全部经 import 验证）:
```
fastapi, uvicorn, pydantic-settings, sqlalchemy, asyncpg,
pymilvus, python-jose, sse-starlette, httpx, openai, pyyaml, loguru
```

---

## 📊 最终修复统计

| 严重级别 | 数量 | Bug 编号 |
|---------|------|----------|
| P0 阻断 | 2 | #1, #2 |
| P1 逻辑/泄漏 | 2 | #3, #4 |
| P2 代码质量 | 6 | #5, #6a, #6b, #7, #8, #9 |

| 改动类型 | 文件数 | 涉及文件 |
|---------|--------|---------|
| 新增文件 | 1 | `backend/app/core/constants.py` |
| 修改文件 | 9 | `generator.py`, `warehouse.py`, `engine.py`, `agent.py`, `scheduler.py`, `planner.py`, `Alerts/index.vue`, `requirements.txt`, `TECH_STACK.md` |

---

## 📝 修复验证

修复后建议运行以下验证：

```bash
# 后端语法检查
cd backend
python -c "from app.core.constants import CST, now_cst; print('constants OK')"
python -c "from app.data.generator import DataGenerator; print('generator OK')"
python -c "from app.data.warehouse import DataWarehouse; print('warehouse OK')"
python -c "from app.agent.engine import AgentEngine; print('engine OK')"
python -c "from app.agent.planner import TaskPlanner; print('planner OK')"

# 前端
cd frontend
npx vite build --mode development 2>&1 | head -20
```
