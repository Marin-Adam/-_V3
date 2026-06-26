"""Agent API — V3.0 Multi-Agent A2A + Streaming + Classic LLM."""

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.engine import AgentEngine
from app.agent.skill_loader import SkillLoader
from app.core.events import sse_manager

router = APIRouter()


class ChatRequest(BaseModel):
    query: str = Field(..., description="用户问题")
    mode: str = Field("auto", description="auto | classic | v3_orchestrator")


class AnalyzeRequest(BaseModel):
    task: str = Field(..., description="分析任务描述")


# ═══════════════════════════════════════════════════════════════════
# V3.0: Streaming Multi-Agent Orchestration (NEW)
# ═══════════════════════════════════════════════════════════════════

@router.post("/orchestrate/stream")
async def agent_orchestrate_stream(request: ChatRequest, req: Request):
    """V3.0 STREAMING multi-agent orchestration via SSE.

    User sees each agent's work in real-time:
      agent_start  → "DataAgent: 正在格式化数据..."
      agent_done   → "DataAgent: 数据处理完成 (订单=35, GMV=¥20,792)"
      agent_start  → "AnalyzeAgent: 正在执行统计分析..."
      agent_done   → "AnalyzeAgent: 发现2个异常"
      ...

    Try it:
      curl -N -X POST http://localhost:8001/api/v1/agent/orchestrate/stream \
        -H "Content-Type: application/json" \
        -d '{"query":"analyze sales anomaly"}'
    """
    if not hasattr(req.app.state, "orchestrator"):
        raise HTTPException(status_code=503, detail="Orchestrator not available")

    orchestrator = req.app.state.orchestrator

    async def event_generator():
        t_start = time.time()
        try:
            async for progress in orchestrator.execute_stream(request.query):
                payload = {
                    "event": progress.event,
                    "agent": progress.agent,
                    "message": progress.message,
                    "data": progress.data,
                    "elapsed_ms": round(progress.elapsed_ms, 0),
                }
                yield {"event": progress.event, "data": json.dumps(payload, ensure_ascii=False)}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}
        finally:
            total_ms = (time.time() - t_start) * 1000
            yield {"event": "done", "data": json.dumps({
                "event": "done",
                "total_ms": round(total_ms, 0),
                "message": f"全部分析完成 (耗时 {total_ms:.0f}ms)",
            })}

    return EventSourceResponse(event_generator())


# ═══════════════════════════════════════════════════════════════════
# Non-streaming endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post("/chat")
async def agent_chat(request: ChatRequest, req: Request):
    """Chat with the AI analyst.

    Modes:
      - v3_orchestrator: V3.0 multi-agent A2A (calls microservices :8010-8013)
      - classic: original AgentEngine (3-tier LLM)
      - auto: orchestrator if available, else classic
    """
    gen = req.app.state.data_generator if hasattr(req.app.state, "data_generator") else None
    streams = req.app.state.stream_manager if hasattr(req.app.state, "stream_manager") else None
    store = req.app.state.data_store if hasattr(req.app.state, "data_store") else None

    # ── V3.0 Orchestrator mode ────────────────────────────────────
    use_orch = (
        request.mode == "v3_orchestrator"
        or (request.mode == "auto" and hasattr(req.app.state, "orchestrator"))
    )

    if use_orch and hasattr(req.app.state, "orchestrator"):
        t0 = time.time()
        orchestrator = req.app.state.orchestrator
        results = await orchestrator.execute(request.query)

        report = results.get("report", {})
        answer = report.get("report", "") if not report.get("fallback") else ""

        # Fallback: if ReportAgent failed, build answer from AnalyzeAgent + DataAgent
        if not answer:
            analyze = results.get("analyze", {})
            data = results.get("data", {})
            if not analyze.get("fallback"):
                answer = f"## 分析结果 (规则引擎)\n\n**{analyze.get('summary','')}**\n\n"
                for f in analyze.get("findings", []):
                    answer += f"- {f}\n"
                for r in analyze.get("recommendations", []):
                    answer += f"- {r}\n"
            elif isinstance(data, dict) and not data.get("fallback"):
                m = data.get("metrics", {})
                answer = f"## 基础数据\n\nGMV ¥{m.get('gmv',0):,.0f} | {m.get('order_count',0)}笔"

        agents_used = ["orchestrator", "data", "analyze", "sentiment", "report"]
        degraded = [k for k, v in results.items()
                    if isinstance(v, dict) and v.get("fallback")]

        return {
            "answer": answer,
            "mode": "v3_orchestrator",
            "agents_used": agents_used,
            "degraded": degraded,
            "data": {k: v for k, v in results.items() if k != "report"},
            "latency_ms": round((time.time() - t0) * 1000, 0),
        }

    # ── Classic mode ─────────────────────────────────────────────
    engine = AgentEngine(data_generator=gen, stream_manager=streams, store=store)
    response = await engine.run(request.query)

    return {
        "answer": response.answer,
        "mode": response.mode,
        "degradation_notice": response.degradation_notice,
        "skills_used": response.skills_used,
        "tools_called": response.tools_called,
        "total_steps": response.total_steps,
        "latency_ms": response.latency_ms,
    }


@router.post("/orchestrate")
async def agent_orchestrate(request: ChatRequest, req: Request):
    """V3.0: Non-streaming multi-agent orchestration."""
    if not hasattr(req.app.state, "orchestrator"):
        raise HTTPException(status_code=503, detail="Orchestrator not available")

    t0 = time.time()
    orchestrator = req.app.state.orchestrator
    results = await orchestrator.execute(request.query)

    report = results.get("report", {})
    answer = report.get("report", "") if not report.get("fallback") else ""

    # Fallback: if ReportAgent failed, use AnalyzeAgent's summary as answer
    if not answer:
        analyze = results.get("analyze", {})
        if not analyze.get("fallback"):
            findings = analyze.get("findings", [])
            summary = analyze.get("summary", "")
            recs = analyze.get("recommendations", [])
            answer = f"## 分析结果 (ReportAgent降级)\n\n**{summary}**\n\n"
            if findings:
                for f in findings:
                    answer += f"- {f}\n"
            if recs:
                answer += "\n### 建议\n"
                for r in recs:
                    answer += f"- {r}\n"
        else:
            data = results.get("data", {})
            metrics = data.get("metrics", {}) if isinstance(data, dict) else {}
            answer = (
                f"## 基础数据\n\n"
                f"GMV: ¥{metrics.get('gmv', 0):,.0f} | "
                f"订单: {metrics.get('order_count', 0)}笔 | "
                f"客单价: ¥{metrics.get('avg_order_value', 0):,.0f}\n\n"
                f"*ReportAgent 不可用，仅展示原始数据*"
            )

    agents_used = ["orchestrator", "data", "analyze", "sentiment", "report"]
    degraded = [k for k, v in results.items()
                if isinstance(v, dict) and v.get("fallback")]

    return {
        "answer": answer,
        "mode": "v3_orchestrator",
        "agents_used": agents_used,
        "degraded": degraded,
        "data": {k: v for k, v in results.items() if k != "report"},
        "latency_ms": round((time.time() - t0) * 1000, 0),
    }


@router.get("/agents/status")
async def agent_status(req: Request):
    """Get real-time status of all A2A agents."""
    import httpx
    agents_cfg = [
        ("data", "http://localhost:8010"),
        ("analyze", "http://localhost:8011"),
        ("sentiment", "http://localhost:8012"),
        ("report", "http://localhost:8013"),
    ]

    statuses = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
        for name, url in agents_cfg:
            try:
                resp = await client.get(f"{url}/health")
                statuses[name] = {
                    "url": url,
                    "online": resp.status_code == 200,
                    "info": resp.json() if resp.status_code == 200 else {},
                }
            except Exception:
                statuses[name] = {"url": url, "online": False}

    return {
        "agents": statuses,
        "orchestrator_available": hasattr(req.app.state, "orchestrator"),
    }


@router.post("/chat/stream")
async def agent_chat_stream(request: ChatRequest, req: Request):
    """Streaming (SSE) classic chat."""
    gen = req.app.state.data_generator if hasattr(req.app.state, "data_generator") else None
    streams = req.app.state.stream_manager if hasattr(req.app.state, "stream_manager") else None
    store = req.app.state.data_store if hasattr(req.app.state, "data_store") else None

    channel = f"agent_{uuid.uuid4().hex[:8]}"
    engine = AgentEngine(data_generator=gen, stream_manager=streams, store=store)

    async def event_generator():
        engine_task = asyncio.create_task(engine.run_stream(request.query, channel))
        try:
            async for sse_event in sse_manager.subscribe(channel):
                yield sse_event
        finally:
            await engine_task

    return EventSourceResponse(event_generator())


@router.get("/skills")
async def list_skills():
    """List all available Agent Skills."""
    loader = SkillLoader()
    return {
        "skills": [
            {
                "name": s.name, "description": s.description,
                "triggers": s.metadata.get("triggers", []),
                "scripts": list(s.scripts.keys()),
                "resources": list(s.resources.keys()),
            }
            for s in loader.list_skills()
        ]
    }


@router.post("/analyze")
async def trigger_analysis(request: AnalyzeRequest, req: Request):
    """Trigger an automated analysis task."""
    gen = req.app.state.data_generator if hasattr(req.app.state, "data_generator") else None
    streams = req.app.state.stream_manager if hasattr(req.app.state, "stream_manager") else None
    store = req.app.state.data_store if hasattr(req.app.state, "data_store") else None

    engine = AgentEngine(data_generator=gen, stream_manager=streams, store=store)
    response = await engine.run(request.task)

    return {
        "task": request.task, "result": response.answer,
        "mode": response.mode,
        "degradation_notice": response.degradation_notice,
        "skills_used": response.skills_used,
        "tools_called": response.tools_called,
        "latency_ms": response.latency_ms,
    }
