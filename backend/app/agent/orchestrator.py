"""Orchestrator — V3.0 Master Agent with intent decomposition + true analysis.

Key difference from V2.0:
  - Understands the USER'S SPECIFIC QUESTION (not just generic analysis)
  - Decomposes intent: what are they asking? which channel/metric/entity?
  - Routes targeted analysis to sub-agents with intent context
  - ReportAgent generates a SPECIFIC answer, not a template
  - LLM-powered when API key available, smart rule-based when not
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Optional

import httpx
from loguru import logger

from app.core.config import get_settings
from app.data.store import PRODUCTS, CHANNELS

settings = get_settings()

AGENT_URLS = {
    "data": settings.DATA_AGENT_URL,
    "analyze": settings.ANALYZE_AGENT_URL,
    "sentiment": settings.SENTIMENT_AGENT_URL,
    "report": settings.REPORT_AGENT_URL,
}


@dataclass
class AgentProgress:
    event: str
    agent: str
    message: str = ""
    data: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0


@dataclass
class Intent:
    """Structured understanding of the user's question."""
    query: str
    focus: str = "general"        # sales / traffic / channel / competitor / anomaly / inventory / general
    target_entity: str = ""       # which channel/product/region they're asking about
    target_metric: str = ""       # gmv / orders / conversion / repurchase
    question_type: str = "what"   # what / why / how / compare / predict
    keywords: list = field(default_factory=list)
    needs_deep_analysis: bool = False  # "why" / "how" questions need deeper investigation


class Orchestrator:
    """Master Agent that UNDERSTANDS the question and orchestrates targeted analysis."""

    def __init__(self, data_generator=None, stream_manager=None, store=None):
        self._gen = data_generator
        self._streams = stream_manager
        self._store = store
        self._client: Optional[httpx.AsyncClient] = None

        # LLM client for deep analysis (optional)
        self._llm = self._init_llm()

        logger.info("Orchestrator: V3.0 ready (A2A HTTP + intent decomposition" +
                    (" + LLM" if self._llm else " + Rule-based") + ")")

    def _init_llm(self):
        """Initialize LLM client if API key is available."""
        try:
            from openai import AsyncOpenAI
            api_key = settings.QWEN_API_KEY or settings.OPENAI_API_KEY or ""
            if len(api_key) > 20:
                base = settings.QWEN_BASE_URL if settings.QWEN_API_KEY else (
                    settings.OPENAI_BASE_URL or "https://api.openai.com/v1")
                return AsyncOpenAI(api_key=api_key, base_url=base)
        except Exception:
            pass
        return None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        return self._client

    # ═══════════════════════════════════════════════════════════════
    # INTENT DECOMPOSITION — the key to understanding questions
    # ═══════════════════════════════════════════════════════════════

    def _parse_intent(self, query: str) -> Intent:
        """Parse user's question into structured intent.

        This is what makes the agent understand SPECIFIC questions
        rather than doing generic analysis every time.
        """
        q = query.lower()
        intent = Intent(query=query, keywords=[])

        # ── Determine FOCUS ───────────────────────────────────────
        if any(w in q for w in ["渠道", "平台", "淘宝", "京东", "拼多多", "抖音", "channel"]):
            intent.focus = "channel"
        elif any(w in q for w in ["竞品", "对手", "竞争", "比价", "competitor"]):
            intent.focus = "competitor"
        elif any(w in q for w in ["库存", "补货", "缺货", "inventory", "stock"]):
            intent.focus = "inventory"
        elif any(w in q for w in ["流量", "uv", "访客", "pv", "转化", "traffic", "conversion"]):
            intent.focus = "traffic"
        elif any(w in q for w in ["复购", "回购", "回头客", "repurchase"]):
            intent.focus = "repurchase"
        elif any(w in q for w in ["异常", "下降", "跌", "降", "问题", "anomaly", "drop"]):
            intent.focus = "anomaly"
        else:
            intent.focus = "sales"

        # ── Extract TARGET ENTITY (channel/product/region) ────────
        for ch in ["淘宝", "京东", "拼多多", "抖音", "小程序", "taobao", "jd"]:
            if ch in q:
                intent.target_entity = ch if ch not in ("taobao", "jd") else (
                    "淘宝" if ch == "taobao" else "京东")
                break
        if not intent.target_entity:
            for p in PRODUCTS:
                pname = p["name"].lower()
                for word in pname.split():
                    if len(word) >= 2 and word in q:
                        intent.target_entity = p["name"]
                        break
                if intent.target_entity:
                    break

        # ── Determine QUESTION TYPE ────────────────────────────────
        if any(w in q for w in ["为什么", "原因", "归因", "怎么回事", "why", "cause"]):
            intent.question_type = "why"
            intent.needs_deep_analysis = True
        elif any(w in q for w in ["怎么", "如何", "怎么办", "建议", "how", "suggest", "recommend"]):
            intent.question_type = "how"
            intent.needs_deep_analysis = True
        elif any(w in q for w in ["对比", "比较", "vs", "compare", "哪个"]):
            intent.question_type = "compare"
            intent.needs_deep_analysis = True
        elif any(w in q for w in ["预测", "趋势", "predict", "forecast"]):
            intent.question_type = "predict"
            intent.needs_deep_analysis = True
        else:
            intent.question_type = "what"

        # ── Extract TARGET METRIC ─────────────────────────────────
        if any(w in q for w in ["gmv", "销售额", "金额", "营收"]):
            intent.target_metric = "gmv"
        elif any(w in q for w in ["订单", "销量", "order"]):
            intent.target_metric = "orders"
        elif any(w in q for w in ["转化", "conversion"]):
            intent.target_metric = "conversion"
        elif any(w in q for w in ["客单价", "avg"]):
            intent.target_metric = "avg_order_value"

        # ── Keywords for sentiment ────────────────────────────────
        intent.keywords = [w for w in re.split(r'[，。？?！!\s]+', q) if len(w) >= 2][:8]

        return intent

    # ═══════════════════════════════════════════════════════════════
    # Streaming execution
    # ═══════════════════════════════════════════════════════════════

    async def execute_stream(self, query: str) -> AsyncGenerator[AgentProgress, None]:
        """Execute with streaming progress — each agent shows its work."""
        t0 = time.time()
        intent = self._parse_intent(query)

        # ── 0. Show intent understanding ──────────────────────────
        yield AgentProgress(
            event="agent_start", agent="orchestrator",
            message=f"理解问题: {query[:60]}",
            elapsed_ms=0,
        )
        yield AgentProgress(
            event="agent_progress", agent="orchestrator",
            message=f"意图识别: focus={intent.focus}, type={intent.question_type}"
                    + (f", target={intent.target_entity}" if intent.target_entity else "")
                    + (" → 需深度分析" if intent.needs_deep_analysis else " → 快速查询"),
            elapsed_ms=(time.time() - t0) * 1000,
        )

        # ── 1. Fetch raw data ─────────────────────────────────────
        raw_data = self._fetch_raw_data(query, intent)
        yield AgentProgress(
            event="agent_progress", agent="orchestrator",
            message=f"已获取数据: {raw_data.get('order_count', 0)} 笔订单, "
                    f"GMV ¥{raw_data.get('gmv', 0):,.0f}, "
                    f"渠道={list(raw_data.get('channel_breakdown', {}).keys())[:5]}",
            data=raw_data,
            elapsed_ms=(time.time() - t0) * 1000,
        )

        # ── 2. DataAgent ──────────────────────────────────────────
        yield AgentProgress(
            event="agent_start", agent="data",
            message="DataAgent: 格式化数据...",
            elapsed_ms=(time.time() - t0) * 1000,
        )
        data_result = await self._call_agent("data", "fetch_metrics", {
            "time_range": "1h",
            "raw_data": raw_data,
            "intent_focus": intent.focus,
        })
        metrics = data_result.get("metrics", {})
        yield AgentProgress(
            event="agent_done", agent="data",
            message=f"DataAgent: {metrics.get('order_count', 0)}笔订单, "
                    f"GMV=¥{metrics.get('gmv',0):,.0f}, "
                    f"客单价=¥{metrics.get('avg_order_value',0):,.0f}",
            data=data_result,
            elapsed_ms=(time.time() - t0) * 1000,
        )

        # ── 3. AnalyzeAgent — TARGETED analysis ───────────────────
        yield AgentProgress(
            event="agent_start", agent="analyze",
            message=f"AnalyzeAgent: 针对「{intent.target_entity or intent.focus}」做定向分析...",
            elapsed_ms=(time.time() - t0) * 1000,
        )
        analyze_result = await self._call_agent("analyze", "analyze", {
            "query": query,
            "intent": {
                "focus": intent.focus,
                "target_entity": intent.target_entity,
                "target_metric": intent.target_metric,
                "question_type": intent.question_type,
                "needs_deep_analysis": intent.needs_deep_analysis,
            },
            "metrics": metrics,
            "breakdown": data_result.get("breakdown", {}),
            "channel_breakdown": data_result.get("channel_breakdown", {}),
            "channel_pcts": data_result.get("channel_pcts", {}),
        })
        anomalies = analyze_result.get("anomalies", [])
        summary = analyze_result.get("summary", "")
        yield AgentProgress(
            event="agent_done", agent="analyze",
            message=f"AnalyzeAgent: {summary[:80]}..."
                    + (f" ({len(anomalies)}个异常)" if anomalies else ""),
            data=analyze_result,
            elapsed_ms=(time.time() - t0) * 1000,
        )

        # ── 4. SentimentAgent ─────────────────────────────────────
        yield AgentProgress(
            event="agent_start", agent="sentiment",
            message="SentimentAgent: 情感分析...",
            elapsed_ms=(time.time() - t0) * 1000,
        )
        sentiment_result = await self._call_agent("sentiment", "analyze_sentiment", {
            "query": query,
            "keywords": intent.keywords,
            "competitor_data": raw_data.get("competitor_snapshots", []),
        })
        yield AgentProgress(
            event="agent_done", agent="sentiment",
            message=f"SentimentAgent: {sentiment_result.get('sentiment_label','?')} "
                    f"(score={sentiment_result.get('sentiment_score',0):.2f})",
            data=sentiment_result,
            elapsed_ms=(time.time() - t0) * 1000,
        )

        # ── 5. ReportAgent — QUESTION-SPECIFIC answer ─────────────
        yield AgentProgress(
            event="agent_start", agent="report",
            message="ReportAgent: 生成针对性分析报告...",
            elapsed_ms=(time.time() - t0) * 1000,
        )
        report_result = await self._call_agent("report", "generate", {
            "query": query,
            "intent": {
                "focus": intent.focus,
                "target_entity": intent.target_entity,
                "question_type": intent.question_type,
                "needs_deep_analysis": intent.needs_deep_analysis,
            },
            "data_result": data_result,
            "analyze_result": analyze_result,
            "sentiment_result": sentiment_result,
        })
        report = report_result.get("report", "")
        yield AgentProgress(
            event="agent_done", agent="report",
            message=f"ReportAgent: 报告完成 ({len(report)}字)",
            data=report_result,
            elapsed_ms=(time.time() - t0) * 1000,
        )

    # ═══════════════════════════════════════════════════════════════
    # Non-streaming (used by /orchestrate endpoint)
    # ═══════════════════════════════════════════════════════════════

    async def execute(self, query: str) -> dict:
        intent = self._parse_intent(query)
        raw_data = self._fetch_raw_data(query, intent)

        # Fetch data first
        data_result = await self._call_agent("data", "fetch_metrics", {
            "time_range": "1h", "raw_data": raw_data, "intent_focus": intent.focus,
        })

        metrics = data_result.get("metrics", {})
        breakdown = data_result.get("breakdown", {})

        # Analyze + Sentiment in parallel
        analyze_task = self._call_agent("analyze", "analyze", {
            "query": query,
            "intent": {
                "focus": intent.focus,
                "target_entity": intent.target_entity,
                "target_metric": intent.target_metric,
                "question_type": intent.question_type,
                "needs_deep_analysis": intent.needs_deep_analysis,
            },
            "metrics": metrics,
            "breakdown": breakdown,
            "channel_breakdown": data_result.get("channel_breakdown", {}),
            "channel_pcts": data_result.get("channel_pcts", {}),
        })
        sentiment_task = self._call_agent("sentiment", "analyze_sentiment", {
            "query": query,
            "keywords": intent.keywords,
            "competitor_data": raw_data.get("competitor_snapshots", []),
        })

        analyze_result, sentiment_result = await asyncio.gather(
            analyze_task, sentiment_task, return_exceptions=True,
        )
        if isinstance(analyze_result, Exception):
            analyze_result = {"fallback": True, "error": str(analyze_result)}
        if isinstance(sentiment_result, Exception):
            sentiment_result = {"fallback": True, "error": str(sentiment_result)}

        # Report (synthesizes everything into a specific answer)
        report_result = await self._call_agent("report", "generate", {
            "query": query,
            "intent": {
                "focus": intent.focus,
                "target_entity": intent.target_entity,
                "question_type": intent.question_type,
                "needs_deep_analysis": intent.needs_deep_analysis,
            },
            "data_result": data_result,
            "analyze_result": analyze_result,
            "sentiment_result": sentiment_result,
        })

        # ── Generate FINAL answer ─────────────────────────────────
        # Priority: LLM (orchestrator's own client) > ReportAgent > AnalyzeAgent fallback
        final_answer = report_result.get("report", "") if not report_result.get("fallback") else ""

        if self._llm:
            try:
                llm_answer = await self._llm_generate(
                    query, intent, data_result, analyze_result, sentiment_result
                )
                if llm_answer:
                    final_answer = llm_answer
                    logger.info("Orchestrator: LLM answer generated ({} chars)", len(llm_answer))
            except Exception as e:
                logger.warning(f"Orchestrator LLM failed: {e}, using agent answer")

        return {
            "data": data_result,
            "analyze": analyze_result,
            "sentiment": sentiment_result,
            "report": {**report_result, "report": final_answer},
            "intent": {
                "focus": intent.focus,
                "target_entity": intent.target_entity,
                "question_type": intent.question_type,
            },
        }

    # ── LLM Answer Generation (runs in main process, reads .env properly) ─

    async def _llm_generate(self, query: str, intent: Intent, data: dict,
                            analyze: dict, sentiment: dict) -> str:
        """Generate final answer using LLM."""
        if not self._llm:
            return ""

        metrics = data.get("metrics", {})
        breakdown = data.get("breakdown", {})

        context = f"""你是电商数据分析专家。根据实时数据直接回答用户问题。

## 用户问题
{query}

## 实时数据
- GMV: ¥{metrics.get('gmv', 0):,.0f}
- 订单量: {metrics.get('order_count', 0)} 笔
- 客单价: ¥{metrics.get('avg_order_value', 0):,.0f}
- 转化率: {metrics.get('conversion_rate', 0):.1f}%
- 渠道分布: {json.dumps(data.get('channel_pcts', {}), ensure_ascii=False)}

## 分析发现
{json.dumps(analyze.get('findings', []), ensure_ascii=False) if not analyze.get('fallback') else '分析Agent不可用'}

## 情感评分
{sentiment.get('sentiment_label', '?')} (score={sentiment.get('sentiment_score', 0):.2f})

请用中文回答，简洁有力（200-400字），用数据说话。"""

        model = settings.QWEN_MODEL if settings.QWEN_API_KEY else "gpt-4o-mini"
        resp = await self._llm.chat.completions.create(
            model=model,
            temperature=0.3,
            max_tokens=600,
            messages=[{"role": "user", "content": context}],
        )
        return resp.choices[0].message.content or ""

    # ═══════════════════════════════════════════════════════════════
    # A2A HTTP Call
    # ═══════════════════════════════════════════════════════════════

    async def _call_agent(self, agent: str, method: str, params: dict) -> dict:
        url = AGENT_URLS.get(agent)
        if not url:
            return {"fallback": True, "error": f"Unknown agent: {agent}"}

        payload = {"jsonrpc": "2.0", "method": method, "params": params,
                    "id": str(int(time.time() * 1000))}
        await asyncio.sleep(0.12)  # realistic network delay

        try:
            client = await self._get_client()
            resp = await client.post(f"{url}/a2a", json=payload,
                                     timeout=settings.A2A_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                return {"fallback": True, "error": str(data["error"])}
            return data.get("result", {})
        except httpx.ConnectError:
            return {"fallback": True, "error": f"{agent} unreachable", "offline": True}
        except asyncio.TimeoutError:
            return {"fallback": True, "error": f"{agent} timeout"}
        except Exception as e:
            return {"fallback": True, "error": str(e)[:100]}

    # ═══════════════════════════════════════════════════════════════
    # Data access
    # ═══════════════════════════════════════════════════════════════

    def _fetch_raw_data(self, query: str, intent: Intent) -> dict:
        """Fetch raw data, optionally filtering by intent target."""
        orders = []
        if self._store:
            orders = self._store.get_recent_orders(60)
        elif self._gen:
            orders = self._gen.get_recent_orders(60)

        # If targeting a specific channel, highlight it
        if intent.target_entity:
            target_lower = intent.target_entity.lower()
            # Mark which orders match the target
            pass  # filtering done downstream

        gmv = sum(o.get("total_amount", 0) for o in orders)

        channel_breakdown = {}
        for o in orders:
            ch = o.get("channel", "unknown")
            channel_breakdown[ch] = channel_breakdown.get(ch, 0) + o.get("total_amount", 0)

        traffic = {}
        if self._store:
            traffic = self._store.get_current_traffic()
        elif self._gen:
            traffic = self._gen.get_current_traffic()
        total_uv = sum(t.get("uv", 0) for t in traffic.values())

        snapshots = []
        if self._store:
            snapshots = self._store.get_recent_competitor_snapshots(20)

        return {
            "order_count": len(orders),
            "gmv": round(gmv, 2),
            "avg_order_value": round(gmv / len(orders), 2) if orders else 0,
            "total_uv": total_uv,
            "channel_breakdown": channel_breakdown,
            "competitor_snapshots": snapshots[:10],
            "timestamp": time.time(),
        }

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
