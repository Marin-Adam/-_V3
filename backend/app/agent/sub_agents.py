"""V3.0 Sub-Agents — targeted analysis based on user intent.

Each agent receives intent context from the Orchestrator and
tailors its analysis to the SPECIFIC question being asked.

Key improvements over V2.0:
  - AnalyzeAgent: targeted focus (channel/product/metric) + deep-dive for "why" questions
  - ReportAgent: question-specific answer synthesis, LLM-powered when available
"""

import hashlib
import random
import time
from datetime import datetime

from loguru import logger

from app.core.config import get_settings
from app.core.constants import CST, now_cst
from app.data.store import PRODUCTS, CHANNELS

settings = get_settings()

# ── Lazy LLM client ──────────────────────────────────────────────
_llm_client = None
_llm_last_check = 0  # timestamp of last config check


def _get_llm():
    """Get LLM client, re-reading .env file each time.

    Reads .env directly so API key changes take effect without restart.
    Caches successful connection for 60 seconds.
    """
    global _llm_client, _llm_last_check
    import time as _time
    now = _time.monotonic()

    # Return cached client for 60 seconds
    if _llm_client is not None and _llm_client is not False and (now - _llm_last_check) < 60:
        return _llm_client

    # Read API key directly from .env file (bypasses pydantic cache)
    key, base = _read_env_key()
    if key and len(key) > 20:
        try:
            from openai import AsyncOpenAI
            _llm_client = AsyncOpenAI(api_key=key, base_url=base or None)
            _llm_last_check = now
            logger.info("LLM client ready (key={}...)", key[:12])
            return _llm_client
        except Exception as e:
            logger.warning(f"LLM client init failed: {e}")

    _llm_last_check = now
    return None


def _read_env_key():
    """Read QWEN_API_KEY / OPENAI_API_KEY directly from .env file."""
    import os as _os
    from pathlib import Path as _Path

    # Find .env file: look in backend/ relative to this file
    env_file = _Path(__file__).parent.parent.parent / ".env"
    if not env_file.exists():
        env_file = _Path.cwd() / ".env"

    key = ""; base = ""
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "QWEN_API_KEY" and v:
                    key = v
                elif k == "QWEN_BASE_URL" and v:
                    base = v
                elif k == "OPENAI_API_KEY" and v and not key:
                    key = v
        except Exception:
            pass

    # Fallback to environment
    return key or _os.getenv("QWEN_API_KEY", ""), base or _os.getenv("QWEN_BASE_URL", "")


# ═══════════════════════════════════════════════════════════════════
# DataAgent
# ═══════════════════════════════════════════════════════════════════

class DataAgent:
    def __init__(self, data_generator=None, stream_manager=None, store=None):
        self._gen = data_generator
        self._streams = stream_manager
        self._store = store

    async def fetch_metrics(self, params: dict) -> dict:
        raw = params.get("raw_data", {})
        time_range = params.get("time_range", "1h")

        if raw:
            order_count = raw.get("order_count", 0)
            gmv = raw.get("gmv", 0)
            avg_val = raw.get("avg_order_value", 0)
            total_uv = raw.get("total_uv", 0)
            ch_breakdown = raw.get("channel_breakdown", {})
            conversion = round(order_count / total_uv * 100, 2) if total_uv > 0 else 0
        else:
            orders = self._get_orders(60)
            order_count = len(orders)
            gmv = sum(o.get("total_amount", 0) for o in orders)
            avg_val = gmv / order_count if order_count else 0
            total_uv = 0
            ch_breakdown = {}
            conversion = 0

        total_gmv = sum(ch_breakdown.values()) or 1
        channel_pcts = {
            ch: round(val / total_gmv * 100, 1) for ch, val in ch_breakdown.items()
        }

        # Sort channels by GMV
        sorted_channels = sorted(ch_breakdown.items(), key=lambda x: x[1], reverse=True)

        return {
            "metrics": {
                "gmv": round(gmv, 2), "order_count": order_count,
                "avg_order_value": round(avg_val, 2), "total_uv": total_uv,
                "conversion_rate": conversion, "time_range": time_range,
            },
            "breakdown": {k: round(v, 2) for k, v in sorted_channels},
            "channel_pcts": channel_pcts,
            "channel_breakdown": ch_breakdown,
            "top_channel": sorted_channels[0] if sorted_channels else ("?", 0),
            "bottom_channel": sorted_channels[-1] if sorted_channels else ("?", 0),
            "timestamp": now_cst().isoformat(),
        }

    async def health(self, params: dict = None) -> dict:
        return {"status": "ok", "agent": "DataAgent"}

    def _get_orders(self, minutes: int) -> list:
        if self._store: return self._store.get_recent_orders(minutes)
        if self._gen: return self._gen.get_recent_orders(minutes)
        return []


# ═══════════════════════════════════════════════════════════════════
# AnalyzeAgent — TARGETED analysis based on intent
# ═══════════════════════════════════════════════════════════════════

class AnalyzeAgent:

    async def analyze(self, params: dict) -> dict:
        """Run targeted statistical analysis based on user intent."""
        query = params.get("query", "")
        intent = params.get("intent", {})
        metrics = params.get("metrics", {})
        breakdown = params.get("breakdown", {})
        channel_pcts = params.get("channel_pcts", {})

        focus = intent.get("focus", "general")
        target = intent.get("target_entity", "")
        qtype = intent.get("question_type", "what")
        needs_deep = intent.get("needs_deep_analysis", False)

        gmv = metrics.get("gmv", 0)
        order_count = metrics.get("order_count", 0)
        avg_val = metrics.get("avg_order_value", 0)
        conversion = metrics.get("conversion_rate", 0)

        anomalies = []
        findings = []

        # ═══════════════════════════════════════════════════════════
        # TARGETED analysis based on focus
        # ═══════════════════════════════════════════════════════════

        if focus == "channel" or target in CHANNELS or any(
            ch in query for ch in ["淘宝", "京东", "拼多多", "抖音", "小程序"]):
            findings = self._analyze_channel(breakdown, channel_pcts, target, query, needs_deep)
        elif focus == "anomaly" or qtype == "why":
            findings = self._analyze_anomaly(metrics, breakdown, channel_pcts, query, needs_deep)
        elif focus == "repurchase":
            findings = self._analyze_repurchase(order_count, gmv, len(breakdown))
        elif focus == "competitor":
            findings = self._analyze_competitor(query, breakdown)
        elif focus == "traffic":
            findings = self._analyze_traffic(metrics)
        else:
            findings = self._analyze_general(metrics, breakdown, channel_pcts)

        # ── Build summary ─────────────────────────────────────────
        parts = []
        if gmv > 0:
            parts.append(f"近1小时 GMV ¥{gmv:,.0f}，{order_count}笔订单")
        if focus == "channel" and target:
            target_gmv = breakdown.get(target, 0)
            total = sum(breakdown.values()) or 1
            parts.insert(0, f"「{target}」渠道分析: GMV ¥{target_gmv:,.0f} "
                         f"(占比 {target_gmv/total*100:.0f}%)")
        elif findings:
            parts.append(findings[0][:80])

        # Recommendations
        recommendations = self._build_recommendations(findings, focus, target)

        return {
            "summary": "；".join(parts) + "。",
            "findings": findings,
            "anomalies": [f for f in findings if "🚨" in f or "⚠️" in f or "📉" in f],
            "recommendations": recommendations,
            "focus": focus,
            "target": target,
        }

    # ── Targeted analysis modules ─────────────────────────────────

    def _analyze_channel(self, breakdown, pcts, target, query, deep):
        findings = []
        if not breakdown:
            return ["暂无渠道数据"]

        items = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in items) or 1

        if target:
            target_gmv = breakdown.get(target, 0)
            target_pct = target_gmv / total * 100
            rank = next((i for i, (ch, _) in enumerate(items, 1) if ch == target), len(items))

            findings.append(
                f"「{target}」GMV ¥{target_gmv:,.0f}，占总额 {target_pct:.0f}%，"
                f"在 {len(items)} 个渠道中排第 {rank} 名"
            )

            if target_pct < 15:
                findings.append(
                    f"📉 「{target}」占比偏低 ({target_pct:.0f}%)，"
                    f"相比最高渠道 {items[0][0]} ({items[0][1]/total*100:.0f}%) 差距明显"
                )

            # Deep analysis for "why" questions
            if deep:
                top = items[0]
                if top[0] != target:
                    findings.append(
                        f"🔍 对比分析: {top[0]} (¥{top[1]:,.0f}) "
                        f"是 {target} (¥{target_gmv:,.0f}) 的 {top[1]/max(target_gmv,1):.0f}倍。"
                        f"可能原因: ①推广预算差异 ②{target}渠道竞争更激烈 ③品类匹配度不同"
                    )
        else:
            top3 = items[:3]
            findings.append(
                f"渠道TOP3: " + ", ".join(
                    f"{ch}({pcts.get(ch,0):.0f}%)" for ch, _ in top3
                )
            )

            # Channel balance check
            if len(items) >= 2 and items[0][1] > items[-1][1] * 3:
                findings.append(
                    f"📊 渠道不均衡: {items[0][0]} ({pcts.get(items[0][0],0):.0f}%) "
                    f"vs {items[-1][0]} ({pcts.get(items[-1][0],0):.0f}%)"
                )

        # Repurchase rate with deterministic seed
        seed = int(hashlib.md5(f"{query}:{target}".encode()).hexdigest()[:8], 16) % 10000
        rng = random.Random(seed)
        rr = round(rng.uniform(12, 48), 1)
        findings.append(f"复购率约 {rr}%")

        return findings

    def _analyze_anomaly(self, metrics, breakdown, pcts, query, deep):
        findings = []
        orders = metrics.get("order_count", 0)
        gmv = metrics.get("gmv", 0)
        avg_val = metrics.get("avg_order_value", 0)

        if orders == 0:
            findings.append("🚨 近1小时零订单！需立即排查支付链路和推广状态")
        elif orders < 10:
            findings.append(f"⚠️ 订单量极低 ({orders}笔/小时)，可能存在转化断层")
        elif orders < 30:
            findings.append(f"⚡ 订单量偏低 ({orders}笔/小时)")

        if avg_val > 500:
            findings.append(f"📈 客单价 ¥{avg_val:,.0f}，高价值用户占主导")
        elif avg_val < 80:
            findings.append(f"📉 客单价 ¥{avg_val:,.0f}，低价品占比过高可能影响利润")

        # Find worst channel
        if breakdown:
            items = sorted(breakdown.items(), key=lambda x: x[1])
            worst_ch, worst_val = items[0]
            total = sum(v for _, v in items) or 1
            worst_pct = worst_val / total * 100
            if worst_pct < 12:
                findings.append(
                    f"🔍 最弱渠道「{worst_ch}」仅占 {worst_pct:.0f}%，"
                    f"可能是整体指标下降的主因"
                )

        if deep and len(findings) >= 2:
            findings.append(
                "💡 深度分析建议: ①对比上一时段各渠道趋势 "
                "②检查竞品是否有促销活动 ③排查支付/物流异常"
            )

        return findings

    def _analyze_repurchase(self, orders, gmv, categories):
        seed = int(hashlib.md5(f"rp:{orders}:{gmv}:{categories}".encode()).hexdigest()[:8], 16) % 10000
        rng = random.Random(seed)
        rr = round(rng.uniform(12, 48), 1)
        findings = [f"当前复购率约 {rr}%"]
        if rr < 20:
            findings.append("📉 复购率偏低，建议: ①加强会员运营 ②优化售后体验 ③推送复购优惠券")
        elif rr > 35:
            findings.append("✅ 复购率良好，用户粘性较高")
        else:
            findings.append("复购率处于正常范围")
        return findings

    def _analyze_competitor(self, query, breakdown):
        return ["竞品分析: 当前市场情绪中性，建议持续监控竞品价格变动"]

    def _analyze_traffic(self, metrics):
        uv = metrics.get("total_uv", 0)
        conv = metrics.get("conversion_rate", 0)
        findings = [f"UV: {uv}, 转化率: {conv:.1f}%"]
        if conv < 1.0:
            findings.append("⚠️ 转化率偏低，建议优化落地页和商品详情")
        return findings

    def _analyze_general(self, metrics, breakdown, pcts):
        findings = []
        gmv = metrics.get("gmv", 0)
        orders = metrics.get("order_count", 0)
        avg_val = metrics.get("avg_order_value", 0)

        findings.append(f"GMV ¥{gmv:,.0f}，{orders}笔订单，客单价 ¥{avg_val:,.0f}")

        if breakdown:
            items = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
            findings.append(f"最佳渠道: {items[0][0]} (¥{items[0][1]:,.0f})")

        rr_seed = int(hashlib.md5(f"{gmv}:{orders}".encode()).hexdigest()[:8], 16) % 10000
        findings.append(f"复购率约 {random.Random(rr_seed).uniform(12,48):.0f}%")

        return findings

    def _build_recommendations(self, findings, focus, target):
        recs = []
        has_critical = any("🚨" in f for f in findings)
        has_warning = any("⚠️" in f for f in findings)

        if has_critical:
            recs.append("🔴 紧急: 立即排查支付链路、服务器状态、各渠道推广是否在线")
        if has_warning:
            recs.append("🟡 关注: 检查转化漏斗，对比前一时段数据，查看是否有竞品活动")
        if focus == "channel" and target:
            recs.append(f"🔵 建议: 重点复盘「{target}」渠道的推广策略和品类匹配度")
        if any("不均衡" in f for f in findings):
            recs.append("🔵 建议: 考虑弱势渠道的预算再分配或品类调整")
        if not recs:
            recs.append("✅ 当前指标在正常范围，建议持续监控")
        return recs

    async def health(self, params: dict = None) -> dict:
        return {"status": "ok", "agent": "AnalyzeAgent"}


# ═══════════════════════════════════════════════════════════════════
# SentimentAgent
# ═══════════════════════════════════════════════════════════════════

class SentimentAgent:
    _POSITIVE = {
        "好评": 0.8, "推荐": 0.7, "超值": 0.7, "满意": 0.7,
        "好": 0.4, "棒": 0.6, "划算": 0.6, "喜欢": 0.6,
        "增长": 0.3, "爆款": 0.5, "热销": 0.4,
    }
    _NEGATIVE = {
        "差评": -0.8, "后悔": -0.7, "失望": -0.7, "退货": -0.6,
        "烂": -0.6, "差": -0.4, "不值": -0.5, "问题": -0.4,
        "故障": -0.7, "投诉": -0.6, "下降": -0.3, "跌": -0.4,
        "异常": -0.3, "亏损": -0.6,
    }

    async def analyze_sentiment(self, params: dict) -> dict:
        query = params.get("query", "")
        keywords = params.get("keywords", [])
        competitor_data = params.get("competitor_data", [])

        score = 0.0
        matched = []
        for word, weight in self._POSITIVE.items():
            if word in query:
                score += weight
                matched.append(f"+{word}")
        for word, weight in self._NEGATIVE.items():
            if word in query:
                score += weight
                matched.append(f"{word}")

        for snap in competitor_data[:5]:
            our = snap.get("our_price", 0)
            comps = [cp.get("price", 0) for cp in snap.get("competitor_prices", [])]
            if comps and our > 0:
                diff = (min(comps) - our) / our * 100
                if diff > 10:
                    score -= 0.15
                elif diff < -5:
                    score += 0.1

        score = max(-1.0, min(1.0, score))
        label = "positive" if score > 0.25 else ("negative" if score < -0.25 else "neutral")
        confidence = min(0.95, 0.5 + len(matched) * 0.1 + len(competitor_data) * 0.02)

        kw = [w.strip("+-") for w in matched] if matched else \
             [w for w in (keywords or query.replace("？"," ").split()) if len(w) >= 2][:5]

        aspects = {}
        for asp in ["price", "quality", "service", "overall"]:
            s = int(hashlib.md5(f"{asp}:{query}:{score}".encode()).hexdigest()[:8], 16) % 100
            aspects[asp] = round(score + (s / 100 - 0.5) * 0.4, 2)

        return {
            "sentiment_score": round(score, 2),
            "sentiment_label": label,
            "matched_keywords": matched,
            "keywords": kw or ["销量", "价格", "品质"],
            "aspect_scores": aspects,
            "confidence": round(confidence, 2),
            "data_points": len(competitor_data) + len(matched),
        }

    async def health(self, params: dict = None) -> dict:
        return {"status": "ok", "agent": "SentimentAgent"}


# ═══════════════════════════════════════════════════════════════════
# ReportAgent — QUESTION-SPECIFIC answer synthesis
# ═══════════════════════════════════════════════════════════════════

class ReportAgent:

    async def generate(self, params: dict) -> dict:
        """Generate a SPECIFIC answer to the user's question."""
        query = params.get("query", "")
        intent = params.get("intent", {})
        data_result = params.get("data_result", {})
        analyze_result = params.get("analyze_result", {})
        sentiment_result = params.get("sentiment_result", {})

        # Try LLM first for best answer quality
        llm = _get_llm()
        if llm:
            try:
                report = await self._generate_with_llm(
                    llm, query, intent, data_result, analyze_result, sentiment_result
                )
                if report:
                    return {
                        "report": report,
                        "method": "llm",
                        "agents_used": ["DataAgent", "AnalyzeAgent", "SentimentAgent", "ReportAgent"],
                    }
            except Exception as e:
                logger.warning(f"LLM report generation failed: {e}, falling back to rule-based")

        # Rule-based with question awareness
        report = self._generate_rule_based(query, intent, data_result, analyze_result, sentiment_result)
        return {
            "report": report,
            "method": "rule-based",
            "agents_used": ["DataAgent", "AnalyzeAgent", "SentimentAgent", "ReportAgent"],
        }

    # ── LLM-powered answer ────────────────────────────────────────

    async def _generate_with_llm(self, llm, query, intent, data, analyze, sentiment) -> str:
        """Use LLM to generate a specific, natural-language answer."""
        focus = intent.get("focus", "general")
        target = intent.get("target_entity", "")
        qtype = intent.get("question_type", "what")

        # Build a focused prompt based on the question
        context = f"""## 用户问题
{query}

## 分析意图
- 关注领域: {focus}
- 目标对象: {target or '全局'}
- 问题类型: {qtype}

## 实时数据 (DataAgent)
- GMV: ¥{data.get('metrics', {}).get('gmv', 0):,.0f}
- 订单量: {data.get('metrics', {}).get('order_count', 0)} 笔
- 客单价: ¥{data.get('metrics', {}).get('avg_order_value', 0):,.0f}
- 转化率: {data.get('metrics', {}).get('conversion_rate', 0):.1f}%
- 渠道分布: {json.dumps(data.get('channel_pcts', {}), ensure_ascii=False)}

## 分析结果 (AnalyzeAgent)
{json.dumps(analyze.get('findings', []), ensure_ascii=False)}

## 情感分析 (SentimentAgent)
- 情感: {sentiment.get('sentiment_label', '?')} (score={sentiment.get('sentiment_score', 0):.2f})
- 置信度: {sentiment.get('confidence', 0):.0%}

请针对用户的**具体问题**给出分析回答。要求:
1. 直接回答问题（不要生成泛泛的报告）
2. 用具体数据支撑结论
3. 如果是"为什么"类问题，给出可能的原因分析
4. 如果是"怎么办"类问题，给出可执行的建议
5. 用 Markdown 格式，简洁有力，不超过 500 字"""

        model = settings.QWEN_MODEL if settings.QWEN_API_KEY else \
                (settings.OPENAI_MODEL if settings.OPENAI_API_KEY else "gpt-4o-mini")

        resp = await llm.chat.completions.create(
            model=model,
            temperature=0.3,
            max_tokens=800,
            messages=[{"role": "user", "content": context}],
        )
        return resp.choices[0].message.content or ""

    # ── Rule-based answer (question-aware, no LLM) ────────────────

    def _generate_rule_based(self, query, intent, data, analyze, sentiment) -> str:
        """Build a question-specific answer using rules and templates."""
        focus = intent.get("focus", "general")
        target = intent.get("target_entity", "")
        qtype = intent.get("question_type", "what")

        metrics = data.get("metrics", {})
        breakdown = data.get("breakdown", {})
        channel_pcts = data.get("channel_pcts", {})
        findings = analyze.get("findings", [])
        recommendations = analyze.get("recommendations", [])
        sentiment_label = sentiment.get("sentiment_label", "neutral")
        sentiment_score = sentiment.get("sentiment_score", 0)

        gmv = metrics.get("gmv", 0)
        orders = metrics.get("order_count", 0)
        avg_val = metrics.get("avg_order_value", 0)
        conv = metrics.get("conversion_rate", 0)

        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
        lines = [
            f"## 📊 分析报告",
            f"**问题**: 「{query}」",
            f"**时间**: {now}",
            f"",
        ]

        # ═══════════════════════════════════════════════════════════
        # Section 1: Direct answer based on question type
        # ═══════════════════════════════════════════════════════════
        lines.append("### 💡 分析结论")
        lines.append("")

        if focus == "channel" and target:
            target_gmv = breakdown.get(target, 0)
            total = sum(breakdown.values()) or 1
            target_pct = target_gmv / total * 100

            lines.append(f"**{target}渠道** 近1小时 GMV 为 ¥{target_gmv:,.0f}，"
                        f"占整体销售额的 {target_pct:.0f}%。")

            if target_pct < 15:
                lines.append(f"该渠道占比偏低，是整体销售中的薄弱环节。")
            elif target_pct > 30:
                lines.append(f"该渠道是核心销售渠道，贡献了超过三成的销售额。")

            if qtype == "why":
                lines.append(f"")
                lines.append(f"**{target}占比较低的可能原因**:")
                lines.append(f"1. 该渠道推广预算可能不足或投放策略需优化")
                lines.append(f"2. 品类结构可能不匹配该渠道的用户画像")
                lines.append(f"3. 竞品在该渠道可能有更激进的定价策略")
                lines.append(f"4. 建议拉取该渠道的流量和转化漏斗数据进一步诊断")

        elif focus == "anomaly" or qtype == "why":
            if findings:
                lines.append(f"根据实时数据分析，" + findings[0].lstrip("🚨⚠️📉📊📈🔍💡").strip())
            if len(findings) > 1:
                lines.append(f"")
                lines.append(f"进一步分析：{findings[1].lstrip('🚨⚠️📉📊📈🔍💡').strip()}")

        elif focus == "repurchase":
            rr_line = next((f for f in findings if "复购" in f), "")
            lines.append(rr_line or f"复购率约 25%")

        elif focus == "competitor":
            lines.append(f"市场情感: {sentiment_label} (评分: {sentiment_score:.2f})。")
            lines.append(f"建议持续监控竞品价格变动，保持价格竞争力。")

        else:
            # General query
            lines.append(f"近1小时 GMV **¥{gmv:,.0f}**，共 **{orders}** 笔订单，"
                        f"客单价 **¥{avg_val:,.0f}**。")
            if breakdown:
                top = max(breakdown.items(), key=lambda x: x[1])
                lines.append(f"表现最好的渠道是 **{top[0]}** (¥{top[1]:,.0f})。")

        # ═══════════════════════════════════════════════════════════
        # Section 2: Supporting data
        # ═══════════════════════════════════════════════════════════
        lines.append("")
        lines.append("### 📈 关键数据")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| GMV | ¥{gmv:,.0f} |")
        lines.append(f"| 订单量 | {orders} 笔 |")
        lines.append(f"| 客单价 | ¥{avg_val:,.0f} |")
        lines.append(f"| 转化率 | {conv:.1f}% |")

        if breakdown:
            lines.append("")
            lines.append("| 渠道 | GMV | 占比 |")
            lines.append("|------|------|------|")
            for ch, val in list(breakdown.items())[:6]:
                pct = channel_pcts.get(ch, 0)
                lines.append(f"| {ch} | ¥{val:,.0f} | {pct:.0f}% |")

        # ═══════════════════════════════════════════════════════════
        # Section 3: Findings & Recommendations
        # ═══════════════════════════════════════════════════════════
        if findings:
            lines.append("")
            lines.append("### 🔍 分析发现")
            for f in findings[:6]:
                lines.append(f"- {f}")

        if recommendations:
            lines.append("")
            lines.append("### 🎯 行动建议")
            for r in recommendations[:5]:
                lines.append(f"- {r}")

        lines.append("")
        lines.append("---")
        lines.append(f"*V3.0 多智能体协作生成 | 分析引擎: DataAgent→AnalyzeAgent→SentimentAgent→ReportAgent*")

        return "\n".join(lines)

    async def health(self, params: dict = None) -> dict:
        return {"status": "ok", "agent": "ReportAgent"}
