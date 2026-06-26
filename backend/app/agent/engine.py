"""Agent engine — three-tier LLM architecture + MCP + Skills + Memory.

Architecture (degradation-aware):
  Tier 1 (Light LLM):  qwen-turbo / gpt-4o-mini — intent routing + simple answers
  Tier 2 (Heavy LLM):  qwen-plus  / gpt-4o        — ReAct deep reasoning
  Tier 3 (Fast mode):  keyword + template engine   — zero-API ultimate fallback

Degradation chain:
  Light fails → try Heavy directly → Heavy fails → Fast with ⚠️ notice

Every degradation step is surfaced to the user so they know the current
capability level.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from app.agent.skill_loader import SkillLoader
from app.core.config import get_settings
from app.core.constants import CST
from app.data.store import PRODUCTS, CHANNELS
from app.mcp.tools import MCPToolExecutor, get_mcp_tools_json

settings = get_settings()

# ── Product / channel / category name → keyword lookup tables ──────
_PRODUCT_KEYWORDS: dict[str, str] = {}
for _p in PRODUCTS:
    for _word in _p["name"].split():
        _PRODUCT_KEYWORDS[_word.lower()] = _p["id"]
    _PRODUCT_KEYWORDS[_p["name"].lower()] = _p["id"]
    _PRODUCT_KEYWORDS[_p["id"].lower()] = _p["id"]

_CHANNEL_NAMES = {ch.lower() for ch in CHANNELS}
_CATEGORY_NAMES = {p["category"].lower() for p in PRODUCTS}


@dataclass
class AgentStep:
    step_num: int
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict] = None
    observation: Optional[str] = None
    skill_used: Optional[str] = None


@dataclass
class AgentResponse:
    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    total_steps: int = 0
    latency_ms: float = 0.0
    memory_refs: list = field(default_factory=list)
    mode: str = "fast"                # "light" | "heavy" | "fast"
    degradation_notice: str = ""      # non-empty means user should see a warning


# ═══════════════════════════════════════════════════════════════════
# Availability checks (three tiers)
# ═══════════════════════════════════════════════════════════════════

def _light_llm_available() -> bool:
    """Check if a lightweight model is configured."""
    key = settings.LIGHT_LLM_API_KEY or settings.QWEN_API_KEY or settings.OPENAI_API_KEY or ""
    return len(key) > 20


def _heavy_llm_available() -> bool:
    """Check if a heavy LLM is configured."""
    return bool(
        (settings.QWEN_API_KEY and len(settings.QWEN_API_KEY) > 20)
        or (settings.OPENAI_API_KEY and len(settings.OPENAI_API_KEY) > 20)
        or (settings.DEEPSEEK_API_KEY and len(settings.DEEPSEEK_API_KEY) > 20)
    )


def _fast_only() -> bool:
    """True when no LLM at all — only keyword Fast mode is available."""
    return not _light_llm_available() and not _heavy_llm_available()


# ═══════════════════════════════════════════════════════════════════
# Lightweight LLM Client (Tier 1)
# ═══════════════════════════════════════════════════════════════════

class LightLLMClient:
    """Cheap, fast model for intent classification and simple Q&A.

    Uses the same OpenAI-compatible SDK as the heavy LLM, but with
    a smaller/cheaper model (e.g. qwen-turbo, gpt-4o-mini).
    """

    # Confidence threshold: below this → route to heavy even if labeled "simple"
    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self):
        key = settings.LIGHT_LLM_API_KEY or settings.QWEN_API_KEY or settings.OPENAI_API_KEY
        base_url = settings.LIGHT_LLM_BASE_URL or settings.QWEN_BASE_URL
        self.model = settings.LIGHT_LLM_MODEL
        self.max_tokens = settings.LIGHT_LLM_MAX_TOKENS
        self.temperature = settings.LIGHT_LLM_TEMPERATURE
        self.client = AsyncOpenAI(api_key=key, base_url=base_url) if key else None
        self._available = key is not None and len(key) > 20

    @property
    def available(self) -> bool:
        return self._available

    async def classify_intent(self, query: str) -> dict:
        """Classify query complexity, intent category, and confidence.

        Returns:
          {"complexity": "simple"|"complex",
           "intent": "sales"|"traffic"|"inventory"|"competitor"|"anomaly"|"general",
           "confidence": 0.0-1.0}
        """
        if not self.client:
            return {"complexity": "simple", "intent": "general", "confidence": 0.0}

        prompt = f"""分析这个电商运营查询。只输出JSON，不要其他文字。

查询: "{query}"

分类规则:
- "complexity": simple = 查数据(数字/排名/状态)，一次性回答就够了
               complex = 需要多步分析、归因、对比、趋势诊断
- "intent": sales(销售GMV/订单) / traffic(流量/转化/UV) / inventory(库存/补货)
            / competitor(竞品/对手) / anomaly(异常/为什么/原因) / general(其他)
- "confidence": 你对分类的信心，0.0-1.0。如果查询模糊、有歧义，打低分

输出严格JSON:
{{"complexity":"<simple或complex>","intent":"<类别>","confidence":<0.0到1.0>}}

示例:
"今天GMV多少" → {{"complexity":"simple","intent":"sales","confidence":0.95}}
"为什么京东转化率连续跌" → {{"complexity":"complex","intent":"anomaly","confidence":0.92}}
"无线耳机" → {{"complexity":"simple","intent":"general","confidence":0.4}}"""

        try:
            resp = await self.client.chat.completions.create(
                model=self.model, temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.choices[0].message.content or "{}"
            import re
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                result = json.loads(match.group(0))
                logger.info(
                    f"Light LLM: query='{query[:60]}' → "
                    f"complexity={result.get('complexity')}, "
                    f"intent={result.get('intent')}, "
                    f"confidence={result.get('confidence')}"
                )
                return result
        except Exception as e:
            logger.warning(f"Light LLM intent classification failed: {e}")

        return {"complexity": "simple", "intent": "general", "confidence": 0.0}

    async def answer_simple(self, query: str, mcp_data: dict, intent: str = "general") -> str:
        """Answer a simple query directly using MCP data context.

        Args:
            query: user's question
            mcp_data: MCP tool results keyed by tool name
            intent: classified intent for data selection
        """
        if not self.client:
            return ""

        prompt = f"""你是电商运营数据分析助手。根据实时数据简要回答用户问题。
一句话说结论 + 关键数字，不多编。

## 实时数据
{json.dumps(mcp_data, ensure_ascii=False, indent=2)}

## 用户问题 ({intent}类查询)
{query}

直接回答（1-3句话）:"""

        try:
            resp = await self.client.chat.completions.create(
                model=self.model, temperature=0.3,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"Light LLM simple answer failed: {e}")
            return ""


# ═══════════════════════════════════════════════════════════════════
# Agent Engine
# ═══════════════════════════════════════════════════════════════════

class AgentEngine:
    """AI Agent with three-tier degradation-aware architecture."""

    def __init__(self, data_generator=None, stream_manager=None, store=None):
        self.mcp = MCPToolExecutor(data_generator, stream_manager, store=store)
        self.skills = SkillLoader()
        self._gen = data_generator
        self._streams = stream_manager
        self._store = store
        self._model = settings.QWEN_MODEL or "qwen-plus"

        # Lazy-init memory
        self._memory = None

        # ── Three-tier LLM setup ──
        self.light_llm = LightLLMClient() if _light_llm_available() else None
        self.heavy_llm = self._create_heavy_llm() if _heavy_llm_available() else None

        # Log startup capability
        tiers = []
        if self.light_llm:
            tiers.append(f"Light({settings.LIGHT_LLM_MODEL})")
        if self.heavy_llm:
            tiers.append(f"Heavy({self._model})")
        tiers.append("Fast(keyword)")
        logger.info(f"Agent engine started — tiers: {' → '.join(tiers)}")

    @property
    def memory(self):
        if self._memory is None:
            from app.agent.memory import AgentMemory
            self._memory = AgentMemory()
        return self._memory

    def _create_heavy_llm(self) -> Optional[AsyncOpenAI]:
        if settings.QWEN_API_KEY and len(settings.QWEN_API_KEY) > 20:
            return AsyncOpenAI(api_key=settings.QWEN_API_KEY, base_url=settings.QWEN_BASE_URL)
        if settings.OPENAI_API_KEY and len(settings.OPENAI_API_KEY) > 20:
            return AsyncOpenAI(api_key=settings.OPENAI_API_KEY,
                               base_url=settings.OPENAI_BASE_URL or None)
        if settings.DEEPSEEK_API_KEY and len(settings.DEEPSEEK_API_KEY) > 20:
            return AsyncOpenAI(api_key=settings.DEEPSEEK_API_KEY,
                               base_url="https://api.deepseek.com/v1")
        return None

    # ═══════════════════════════════════════════════════════════════
    # Public API — three-tier routing with degradation
    # ═══════════════════════════════════════════════════════════════

    # ── Explicit conditions: queries that MUST go to heavy ──────────
    _COMPLEX_KEYWORDS = [
        "为什么", "原因", "归因", "根因", "怎么回事", "什么导致",
        "分析", "诊断", "排查", "深挖", "对比",
        "连续", "一直", "趋势", "变化", "波动",
        "怎么办", "怎么", "如何优化", "如何提升", "如何解决", "建议",
    ]

    def _is_obviously_complex(self, query: str) -> bool:
        """Keyword pre-filter: queries that clearly need multi-step reasoning.

        These bypass the light model entirely — no point asking an LLM
        to classify something that's obviously complex.
        """
        q = query.lower()
        return any(kw in q for kw in self._COMPLEX_KEYWORDS)

    async def run(self, query: str, chat_history: str = "") -> AgentResponse:
        """Route query through available tiers with graceful degradation.

        Routing logic (three-layer defense):
          1. Keyword pre-filter → obviously complex? → skip light, go heavy
          2. Light LLM semantic classification → simple or complex?
          3. Confidence gate → confidence < threshold? → route to heavy anyway
        """
        degradation: list[str] = []

        # ── Tier 1: Light LLM → intent routing ─────────────────────
        if self.light_llm and self.light_llm.available:

            # ═══════════════════════════════════════════════════════
            # Layer 1: Keyword pre-filter
            #   "为什么连跌" → don't waste API call on light model
            # ═══════════════════════════════════════════════════════
            if self._is_obviously_complex(query):
                logger.info(f"Keyword pre-filter: query is obviously complex → skip light")
                if self.heavy_llm:
                    return await self._run_llm(query, chat_history, degradation)
                # Heavy not available → ask light to try anyway
                degradation.append("检测到复杂查询但主力LLM未配置→轻量模型尽力回答")

            # ═══════════════════════════════════════════════════════
            # Layer 2: Light LLM semantic classification
            # ═══════════════════════════════════════════════════════
            if not degradation:  # not already routed
                try:
                    intent = await self.light_llm.classify_intent(query)
                    complexity = intent.get("complexity", "simple")
                    confidence = intent.get("confidence", 0)
                    intent_type = intent.get("intent", "general")

                    # ═══════════════════════════════════════════════
                    # Layer 3: Confidence gate
                    #   Low confidence → don't trust "simple" label
                    # ═══════════════════════════════════════════════
                    if (complexity == "simple"
                            and confidence >= LightLLMClient.CONFIDENCE_THRESHOLD):
                        # ── Simple + high confidence → light handles it ──
                        mcp_data = await self._fetch_intent_data(intent_type)
                        answer = await self.light_llm.answer_simple(
                            query, mcp_data, intent=intent_type
                        )
                        if answer:
                            try:
                                await self.memory.store(
                                    content=f"用户问题: {query}\n\n{answer}",
                                    metadata={"query": query, "mode": "light",
                                              "intent": intent_type,
                                              "timestamp": datetime.now(CST).isoformat()},
                                )
                            except Exception:
                                pass
                            return AgentResponse(
                                answer=answer, mode="light",
                                latency_ms=0, total_steps=1,
                            )

                    else:
                        # ── Complex OR low confidence → route to Heavy ──
                        reason = (
                            f"complexity={complexity}" if complexity == "complex"
                            else f"confidence={confidence:.2f}<{LightLLMClient.CONFIDENCE_THRESHOLD}"
                        )
                        logger.info(f"Routing to Heavy LLM ({reason})")

                        if self.heavy_llm:
                            return await self._run_llm(query, chat_history, degradation)

                        # Heavy not available → light tries anyway with notice
                        degradation.append(
                            f"主力LLM未配置→轻量模型处理复杂查询（{reason}，分析深度受限）"
                        )
                        mcp_data = await self._fetch_intent_data(intent_type)
                        answer = await self.light_llm.answer_simple(
                            f"请尽力做深度分析: {query}", mcp_data, intent=intent_type
                        )
                        return AgentResponse(
                            answer=answer or "分析失败", mode="light",
                            degradation_notice="; ".join(degradation),
                            latency_ms=0, total_steps=1,
                        )

                except Exception as e:
                    logger.warning(f"Tier 1 (Light LLM) failed: {e}")
                    degradation.append("轻量模型异常→尝试主力LLM")

        # ── Tier 2: Heavy LLM directly ─────────────────────────────
        if self.heavy_llm:
            if degradation:
                logger.info(f"Routing to Heavy LLM (degradation: {degradation})")
            return await self._run_llm(query, chat_history, degradation)

        # ── Tier 3: Fast mode — ultimate fallback ─────────────────
        if not degradation:
            degradation.append("未配置任何LLM API Key→Fast规则模式")
        else:
            degradation.append("所有LLM不可用→降级到Fast规则模式（分析能力受限）")

        response = await self._run_fast(query)
        response.degradation_notice = "; ".join(degradation)
        response.mode = "fast"
        return response

    async def _fetch_intent_data(self, intent_type: str) -> dict:
        """Fetch MCP data based on classified intent.

        Different intent → different data needed. Avoids fetching
        unnecessary data for simple queries.
        """
        mcp_data = {}

        # Always pull sales baseline (cheap, always useful)
        try:
            mcp_data["sales"] = await self.mcp.execute(
                "query_sales_metrics", {"time_range": "1h"}
            )
        except Exception:
            pass

        # Intent-specific data
        if intent_type == "traffic":
            try:
                mcp_data["traffic"] = await self.mcp.execute(
                    "query_traffic_data", {"time_range": "1h"}
                )
            except Exception:
                pass

        elif intent_type == "inventory":
            try:
                mcp_data["inventory"] = await self.mcp.execute(
                    "query_inventory", {"alert_only": True}
                )
            except Exception:
                pass

        elif intent_type == "competitor":
            try:
                mcp_data["competitor"] = await self.mcp.execute(
                    "query_competitor_prices", {}
                )
            except Exception:
                pass

        elif intent_type == "anomaly":
            # Anomaly means user is asking about a problem → bring channel data
            try:
                mcp_data["traffic"] = await self.mcp.execute(
                    "query_traffic_data", {"time_range": "1h"}
                )
                mcp_data["channel"] = await self.mcp.execute(
                    "execute_analytics_query",
                    {"metric": "gmv", "dimension": "channel"}
                )
            except Exception:
                pass

        # "sales" and "general" → just sales baseline (already fetched)
        return mcp_data

    async def run_stream(self, query: str, channel: str, chat_history: str = ""):
        """SSE streaming wrapper with mode awareness."""
        from app.core.events import sse_manager

        mode = "light" if (self.light_llm and self.light_llm.available) else \
               ("heavy" if self.heavy_llm else "fast")

        try:
            await sse_manager.publish(channel, json.dumps({
                "event": "agent_start", "query": query, "mode": mode,
            }))
            response = await self.run(query, chat_history)
            await sse_manager.publish(channel, json.dumps({
                "event": "agent_done", "answer": response.answer,
                "mode": response.mode,
                "degradation_notice": response.degradation_notice,
                "skills_used": response.skills_used,
                "tools_called": response.tools_called,
                "total_steps": response.total_steps,
                "latency_ms": response.latency_ms,
            }))
        except Exception as e:
            await sse_manager.publish(channel, json.dumps({
                "event": "error", "error": str(e),
            }))
        finally:
            await sse_manager.close_channel(channel)

    # ═══════════════════════════════════════════════════════════════
    # Fast Mode (Tier 3) — fuzzy intent + parallel MCP + memory
    # ═══════════════════════════════════════════════════════════════

    async def _run_fast(self, query: str) -> AgentResponse:
        """Fuzzy-intent analysis with parallel MCP calls and memory search."""
        start_time = time.time()
        steps: list[AgentStep] = []
        tools_called: list[str] = []
        skills_used: list[str] = []
        memory_refs: list = []

        q = query.lower()

        # ── Step 0: Memory search ──────────────────────────────────
        try:
            past = await self.memory.search(query, top_k=3)
            if past:
                memory_refs = [
                    {"content": p.content[:200], "metadata": p.metadata}
                    for p in past
                ]
        except Exception as e:
            logger.debug(f"Memory search skipped: {e}")

        # ── Step 1: Detect intents + parallel MCP ──────────────────
        step_num = 0
        data: dict = {}

        # Always pull sales baseline
        step_num += 1
        sales = await self.mcp.execute("query_sales_metrics", {"time_range": "1h"})
        steps.append(AgentStep(step_num=step_num, thought="获取销售概览",
                               action="query_sales_metrics", action_input={"time_range": "1h"},
                               observation=json.dumps(sales, ensure_ascii=False, indent=2)))
        tools_called.append("query_sales_metrics")
        skills_used.append("sales-anomaly-detection")
        data["sales"] = sales

        intents = self._detect_intents(q)

        coros = {}
        intent_labels = {}

        if intents.get("traffic"):
            coros["traffic"] = self.mcp.execute("query_traffic_data", {"time_range": "1h"})
            intent_labels["traffic"] = ("获取流量数据", "query_traffic_data")
        if intents.get("inventory"):
            coros["inventory"] = self.mcp.execute("query_inventory", {"alert_only": True})
            intent_labels["inventory"] = ("查询库存水位", "query_inventory")
            skills_used.append("inventory-optimizer")
        if intents.get("competitor"):
            coros["competitor"] = self.mcp.execute("query_competitor_prices", {})
            intent_labels["competitor"] = ("查询竞品价格", "query_competitor_prices")
            skills_used.append("competitor-monitor")
        if intents.get("channel") or intents.get("category"):
            dim = "channel" if intents.get("channel") else "category"
            coros["dim"] = self.mcp.execute("execute_analytics_query",
                                            {"metric": "gmv", "dimension": dim})
            intent_labels["dim"] = (f"{dim}维度分析", "execute_analytics_query")

        if coros:
            results = await asyncio.gather(*coros.values(), return_exceptions=True)
            for (key, coro), result in zip(coros.items(), results):
                if isinstance(result, Exception):
                    logger.error(f"MCP call {key} failed: {result}")
                    continue
                step_num += 1
                thought, action = intent_labels[key]
                steps.append(AgentStep(
                    step_num=step_num, thought=thought, action=action, action_input={},
                    observation=json.dumps(result, ensure_ascii=False, indent=2),
                ))
                tools_called.append(action)
                data[key] = result

        # ── Step 2: Deep drill on anomalies ───────────────────────
        if intents.get("anomaly"):
            step_num += 1
            channel_data = data.get("dim") or await self.mcp.execute(
                "execute_analytics_query", {"metric": "gmv", "dimension": "channel"})
            steps.append(AgentStep(step_num=step_num, thought="异常下钻: 渠道分布",
                                   action="execute_analytics_query",
                                   observation=json.dumps(channel_data, ensure_ascii=False, indent=2)))
            tools_called.append("execute_analytics_query")
            data["drill_channel"] = channel_data

            results_list = channel_data.get("results", [])
            if results_list:
                worst = results_list[-1]
                worst_channel = worst.get("key", "")
                if worst_channel:
                    step_num += 1
                    cat_data = await self.mcp.execute(
                        "execute_analytics_query",
                        {"metric": "gmv", "dimension": "category"})
                    steps.append(AgentStep(
                        step_num=step_num, thought=f"异常下钻: 品类分布 ({worst_channel})",
                        action="execute_analytics_query",
                        observation=json.dumps(cat_data, ensure_ascii=False, indent=2),
                    ))
                    tools_called.append("execute_analytics_query")
                    data["drill_category"] = cat_data

            step_num += 1
            top_products = await self.mcp.execute("execute_analytics_query",
                                                  {"metric": "gmv", "dimension": "product", "top_n": 10})
            steps.append(AgentStep(step_num=step_num, thought="异常下钻: 热销商品排行",
                                   action="execute_analytics_query",
                                   observation=json.dumps(top_products, ensure_ascii=False, indent=2)))
            tools_called.append("execute_analytics_query")
            data["drill_product"] = top_products

        # ── Step 3: Build report ──────────────────────────────────
        answer = self._build_fast_answer(query, data, sales, memory_refs)

        # ── Step 4: Store in memory ───────────────────────────────
        try:
            await self.memory.store(
                content=f"用户问题: {query}\n\n{answer}",
                metadata={
                    "query": query,
                    "skills_used": list(set(skills_used)),
                    "tools_called": list(set(tools_called)),
                    "timestamp": datetime.now(CST).isoformat(),
                },
            )
        except Exception as e:
            logger.debug(f"Memory store skipped: {e}")

        latency = (time.time() - start_time) * 1000
        return AgentResponse(
            answer=answer, steps=steps, mode="fast",
            skills_used=list(set(skills_used)),
            tools_called=list(set(tools_called)),
            total_steps=len(steps), latency_ms=latency,
            memory_refs=memory_refs,
        )

    def _detect_intents(self, q: str) -> dict[str, bool]:
        """Fuzzy multi-intent detection from natural language query."""
        intents: dict[str, bool] = {}

        if any(kw in q for kw in ["异常", "下降", "跌", "降", "问题", "告警", "预警",
                                    "怎么", "为什么", "原因", "分析", "排查"]):
            intents["anomaly"] = True

        if any(kw in q for kw in ["流量", "uv", "访客", "pv", "转化", "点击", "浏览"]):
            intents["traffic"] = True

        if any(kw in q for kw in ["库存", "补货", "缺货", "清仓", "备货", "囤货"]):
            intents["inventory"] = True

        if any(kw in q for kw in ["竞品", "竞争", "对手", "价格战", "比价",
                                    "别人", "他们", "同行"]):
            intents["competitor"] = True

        for ch_name in _CHANNEL_NAMES:
            if ch_name in q:
                intents["channel"] = True
                break
        if not intents.get("channel") and any(kw in q for kw in ["渠道", "平台"]):
            intents["channel"] = True

        for cat_name in _CATEGORY_NAMES:
            if cat_name in q:
                intents["category"] = True
                break
        if not intents.get("category") and any(kw in q for kw in ["品类", "类目", "分类"]):
            intents["category"] = True

        for kw in q.replace("？", " ").replace("?", " ").replace("，", " ").split():
            kw = kw.strip()
            if kw in _PRODUCT_KEYWORDS:
                intents["specific_product"] = True
                break
        if not intents.get("specific_product"):
            for p_name in [p["name"].lower() for p in PRODUCTS]:
                parts = [w for w in p_name.split() if len(w) >= 2]
                if any(part in q for part in parts):
                    intents["specific_product"] = True
                    break

        logger.debug(f"Detected intents: {dict(intents)} for query: {q[:80]}")
        return intents

    def _build_fast_answer(self, query: str, data: dict, sales: dict,
                           memory_refs: list = None) -> str:
        """Generate structured analysis report."""
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
        gmv = sales.get("gmv", 0)
        orders = sales.get("order_count", 0)
        avg_val = sales.get("avg_order_value", 0)

        lines = [
            f"## 📊 电商实时分析报告",
            f"**分析时间**: {now} (北京时间) | **模式**: ⚡Fast规则模式",
        ]

        if memory_refs:
            lines.append("")
            lines.append("### 🧠 历史相关分析")
            lines.append("")
            for i, ref in enumerate(memory_refs[:2], 1):
                snippet = ref.get("content", "")[:150]
                if snippet:
                    lines.append(f"> 📝 **参考{i}**: {snippet}...")
            lines.append("")

        q_lower = query.lower()
        if any(kw in q_lower for kw in ["异常", "下降", "跌", "降", "问题"]):
            lines.insert(1, f"> 🔍 **针对**: 「{query}」— 已自动拉取销售数据并下钻分析。")
        else:
            lines.insert(1, f"> 💬 **问题**: 「{query}」")

        lines.append("")
        lines.append("### 📈 核心指标概览")
        lines.append("")
        lines.append("| 指标 | 数值 | 说明 |")
        lines.append("|------|------|------|")
        lines.append(f"| **GMV** | ¥{gmv:,.2f} | 近1小时销售额 |")
        lines.append(f"| **订单量** | {orders} 笔 | 近1小时 |")
        lines.append(f"| **客单价** | ¥{avg_val:,.2f} | 平均每单金额 |")

        ch = sales.get("channel_breakdown", {})
        if ch:
            lines.append("")
            lines.append("### 🏪 渠道销售分布")
            lines.append("")
            lines.append("| 渠道 | GMV | 占比 |")
            lines.append("|------|------|------|")
            total_gmv = sum(ch.values()) or 1
            for name, val in sorted(ch.items(), key=lambda x: x[1], reverse=True):
                pct = val / total_gmv * 100
                bar = "█" * int(pct / 5)
                lines.append(f"| {name} | ¥{val:,.0f} | {bar} {pct:.1f}% |")

        if sales.get("order_count", 0) > 0:
            from app.data.warehouse import DataWarehouse
            wh = DataWarehouse()
            wh._gen = self._gen
            wh._streams = self._streams
            baseline = wh.get_rolling_baseline(60)
            if baseline > 0:
                current_5m_gmv = sales.get("gmv", 0)
                dev = (current_5m_gmv - baseline) / baseline
                if abs(dev) > 0.15:
                    severity = "P0" if abs(dev) > 0.5 else ("P1" if abs(dev) > 0.3 else "P2")
                    direction = "上升" if dev > 0 else "下降"
                    emoji = {"P0": "🔴", "P1": "🟡", "P2": "🔵"}.get(severity, "⚪")
                    lines.append("")
                    lines.append("### ⚠️ 异常预警")
                    lines.append("")
                    lines.append(
                        f"> {emoji} **{severity}**: GMV {direction}{abs(dev)*100:.0f}% "
                        f"(当前5分钟 ¥{current_5m_gmv:,.0f} vs 基线 ¥{baseline:,.0f})"
                    )

                    drill_ch = data.get("drill_channel", {}).get("results", [])
                    drill_cat = data.get("drill_category", {}).get("results", [])
                    drill_prod = data.get("drill_product", {}).get("results", [])

                    if drill_ch:
                        worst_ch = drill_ch[-1]
                        lines.append(f"> 📉 **最弱渠道**: {worst_ch['key']} — GMV ¥{worst_ch['value']:,.0f}")
                    if drill_cat:
                        worst_cat = drill_cat[-1]
                        lines.append(f"> 📂 **最弱品类**: {worst_cat['key']} — GMV ¥{worst_cat['value']:,.0f}")
                    if drill_prod:
                        lines.append("")
                        lines.append("**🔥 Top 3 热销商品**:")
                        for i, p in enumerate(drill_prod[:3], 1):
                            lines.append(f"  {i}. {p['key']} — ¥{p['value']:,.0f}")

                    lines.append("")
                    lines.append(f"> 💡 **建议**: ", end="")
                    if drill_ch and worst_ch["key"] != "unknown":
                        lines[-1] += f"重点排查 **{worst_ch['key']}渠道** 投放与转化情况。"
                    if drill_cat:
                        worst_cat_name = drill_cat[-1]["key"]
                        if worst_cat_name != "unknown":
                            lines[-1] += f"关注 **{worst_cat_name}品类** 库存与定价。"
                    if severity == "P0":
                        lines[-1] += " 建议立即通知运营负责人排查支付链路。"
                    lines.append("")

        inv = data.get("inventory", {}).get("inventory", [])
        low_stock = [i for i in inv if i.get("alert")]
        if low_stock:
            lines.append("")
            lines.append("### 📦 库存预警")
            lines.append("")
            lines.append("| 商品ID | 库存 | 状态 |")
            lines.append("|--------|------|------|")
            for item in low_stock[:8]:
                alert_label = "🚨 紧急" if item["quantity"] < 10 else "⚠️ 偏低"
                lines.append(f"| {item['product_id']} | {item['quantity']} 件 | {alert_label} |")

        comp = data.get("competitor", {}).get("competitor_data", [])
        if comp:
            lines.append("")
            lines.append("### 👀 竞品动态")
            lines.append("")
            for entry in comp[:3]:
                our = entry.get("our_price", 0)
                comps = entry.get("competitor_prices", [])
                if comps:
                    min_comp = min(cp["price"] for cp in comps)
                    diff = (min_comp - our) / our * 100 if our > 0 else 0
                    flag = "🟢 有优势" if diff > 5 else ("🔴 劣势" if diff < -10 else "🟡 持平")
                    lines.append(
                        f"- {entry.get('product_name', '?')}: 我方 ¥{our}, "
                        f"最低竞品 ¥{min_comp} ({flag}, 差{abs(diff):.0f}%)"
                    )
            if len(comp) > 3:
                lines.append(f"- ... 还有 {len(comp)-3} 条竞品记录")

        lines.append("")
        lines.append("### 💡 行动建议")
        lines.append("")

        rec_num = 1
        if orders < 50:
            lines.append(f"{rec_num}. 🔍 订单量偏低 ({orders}笔/小时)，建议检查所有渠道推广状态")
            rec_num += 1
        else:
            lines.append(f"{rec_num}. ✅ 当前销售节奏正常 ({orders}笔/小时)，持续监控")
            rec_num += 1

        if ch:
            sorted_ch = sorted(ch.items(), key=lambda x: x[1])
            if len(sorted_ch) >= 2:
                best_ch, best_val = sorted_ch[-1]
                worst_ch_name, worst_val = sorted_ch[0]
                if best_val > worst_val * 3:
                    lines.append(f"{rec_num}. 📊 {best_ch}(¥{best_val:,.0f}) 是 {worst_ch_name}(¥{worst_val:,.0f}) 的 {best_val/worst_val:.0f}倍，建议复盘{worst_ch_name}运营策略")
                    rec_num += 1

        if low_stock:
            lines.append(f"{rec_num}. 🛒 {len(low_stock)} 个商品库存偏低，优先补货")
            rec_num += 1

        if comp:
            lines.append(f"{rec_num}. 👀 竞品活跃，建议每30分钟检查一次价格竞争力")
            rec_num += 1

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════
    # LLM Mode (Tier 2) — memory-injected system prompt + ReAct loop
    # ═══════════════════════════════════════════════════════════════

    async def _run_llm(self, query: str, chat_history: str = "",
                       degradation: list[str] | None = None) -> AgentResponse:
        start_time = time.time()
        steps, skills_used, tools_called, memory_refs = [], [], [], []
        degradation = degradation or []

        # ── Fetch memory context ──────────────────────────────────
        memory_context = ""
        try:
            past = await self.memory.search(query, top_k=3)
            if past:
                memory_refs = [{"content": p.content[:200], "metadata": p.metadata} for p in past]
                memory_context = "\n".join(
                    f"- [{i+1}] {p.content[:300]}" for i, p in enumerate(past)
                )
        except Exception as e:
            logger.debug(f"Memory search skipped: {e}")

        # ── Fetch active alerts ───────────────────────────────────
        alert_context = ""
        try:
            from app.data.warehouse import DataWarehouse
            wh = DataWarehouse()
            wh._gen = self._gen
            wh._streams = self._streams
            open_alerts = await wh.get_open_alerts()
            if open_alerts:
                alert_lines = []
                for a in open_alerts[:5]:
                    alert_lines.append(
                        f"- [{a['severity']}] {a['title']} ({a.get('created_at', '?')})"
                    )
                alert_context = "当前活跃告警:\n" + "\n".join(alert_lines)
        except Exception:
            pass

        system_prompt = self._build_system_prompt(memory_context, alert_context)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"对话历史:\n{chat_history or '(无)'}\n\n用户问题:\n{query}"},
        ]

        final_answer = ""
        for step_num in range(1, min(settings.AGENT_MAX_STEPS, 5) + 1):
            response = await self.heavy_llm.chat.completions.create(
                model=self._model, messages=messages,
                tools=get_mcp_tools_json(),
                tool_choice="auto", temperature=0.1, max_tokens=1024,
            )
            choice = response.choices[0]

            if choice.message.tool_calls:
                tool_coros = {}
                tool_metas = {}
                for tc in choice.message.tool_calls[:3]:
                    try:
                        params = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        params = {}
                    tool_coros[tc.id] = self.mcp.execute(tc.function.name, params)
                    tool_metas[tc.id] = (tc.function.name, params)

                tool_results = await asyncio.gather(
                    *tool_coros.values(), return_exceptions=True,
                )

                for tc, result in zip(choice.message.tool_calls, tool_results):
                    if isinstance(result, Exception):
                        result = {"error": str(result)}
                    tool_name = tool_metas[tc.id][0]
                    params = tool_metas[tc.id][1]

                    step = AgentStep(
                        step_num=step_num,
                        thought=choice.message.content or f"调用工具: {tool_name}",
                        action=tool_name, action_input=params,
                        observation=json.dumps(result, ensure_ascii=False, indent=2),
                    )
                    steps.append(step)
                    tools_called.append(tool_name)

                    for skill in self.skills.list_skills():
                        if tool_name in skill.metadata.get("depends_on", []):
                            skills_used.append(skill.name)

                    messages.append({
                        "role": "assistant", "content": choice.message.content,
                        "tool_calls": [{
                            "id": tc.id, "type": "function",
                            "function": {"name": tool_name, "arguments": tc.function.arguments},
                        }],
                    })
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": step.observation,
                    })
            else:
                final_answer = choice.message.content or ""
                steps.append(AgentStep(step_num=step_num, thought="生成分析结论",
                                       observation=final_answer))
                break
        else:
            final_answer = "已收集足够数据。请基于以上数据分析关键指标和异常情况。"

        # ── Store in memory ────────────────────────────────────────
        try:
            await self.memory.store(
                content=f"用户问题: {query}\n\n{final_answer}",
                metadata={
                    "query": query, "mode": "heavy",
                    "skills_used": list(set(skills_used)),
                    "tools_called": list(set(tools_called)),
                    "timestamp": datetime.now(CST).isoformat(),
                },
            )
        except Exception:
            pass

        latency = (time.time() - start_time) * 1000
        return AgentResponse(
            answer=final_answer or "暂无分析结论", steps=steps, mode="heavy",
            skills_used=list(set(skills_used)),
            tools_called=list(set(tools_called)),
            total_steps=len(steps), latency_ms=latency,
            memory_refs=memory_refs,
            degradation_notice="; ".join(degradation) if degradation else "",
        )

    def _build_system_prompt(self, memory_context: str = "", alert_context: str = "") -> str:
        skills_desc = self.skills.get_skills_for_prompt() if self.skills.list_skills() else ""

        prompt = f"""你是电商数据AI分析专家。用MCP工具获取真实数据进行分析。

{skills_desc}

## 分析原则
1. **数据优先**: 主动用工具获取数据，基于数据说话（不编造数字）
2. **结构化输出**: Markdown格式，含核心结论→详细分析→行动建议
3. **深挖根因**: 发现异常后自动下钻（渠道→品类→商品），定位问题源头
4. **可执行建议**: 每条建议具体到渠道/商品/金额，运营可直接执行"""

        if memory_context:
            prompt += f"""

## 历史相似分析（供参考）
{memory_context}

请参考历史案例的分析框架，但基于当前实际数据给出结论。"""

        if alert_context:
            prompt += f"""

{alert_context}"""

        prompt += """

## 输出格式
1. **一句话结论** (核心发现)
2. **详细分析** (数据表格 + 趋势解读)
3. **行动建议** (按优先级排列，具体可执行)"""

        return prompt
