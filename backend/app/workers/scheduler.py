"""Background task scheduler — periodically triggers Skills and manages alerts.

Complete anomaly closed loop:
  1. 定时检测 (每5分钟):  MCP 获取真实数据 → 计算偏离度 → 分级 → 写库 + 推送 + 记忆
  2. 异常升级 (每10分钟): P0/P1/P2 超时未处理 → 升级严重级别
  3. 竞品监控 (每5分钟): MCP 获取竞品数据 → 价格劣势检测 → 预警
  4. 库存检查 (每30分钟): MCP 获取库存 → 低库存预警
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from app.agent.skill_loader import SkillLoader
from app.core.config import get_settings
from app.core.constants import CST, now_cst
from app.mcp.tools import MCPToolExecutor

settings = get_settings()


class SkillScheduler:
    """Runs Skills on configurable intervals with complete alert lifecycle."""

    def __init__(self, data_generator=None, stream_manager=None, store=None):
        self.skills = SkillLoader()
        self.mcp = MCPToolExecutor(data_generator, stream_manager, store=store)
        self._memory = None  # lazy init (avoids asyncpg import if PG is down)
        self._gen = data_generator
        self._streams = stream_manager
        self._store = store
        self._tasks: list[asyncio.Task] = []
        self._running = False

    @property
    def memory(self):
        """Lazy-init AgentMemory — avoids crashing when asyncpg is not installed."""
        if self._memory is None:
            from app.agent.memory import AgentMemory
            self._memory = AgentMemory()
        return self._memory

    async def start(self):
        self._running = True
        # Core monitoring
        self._tasks.append(asyncio.create_task(self._run_anomaly_detection()))
        self._tasks.append(asyncio.create_task(self._run_alert_escalation()))
        self._tasks.append(asyncio.create_task(self._run_competitor_monitor()))
        self._tasks.append(asyncio.create_task(self._run_inventory_check()))
        logger.info("SkillScheduler started (4 periodic tasks): anomaly + escalation + competitor + inventory")

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ═══════════════════════════════════════════════════════════════
    # 销售异常检测 (每5分钟) — 完整闭环
    # ═══════════════════════════════════════════════════════════════

    async def _run_anomaly_detection(self):
        """Detect sales anomalies with real MCP data every 5 minutes.

        Pipeline:
          MCP data → deviation calc → classify → save_alert → push notify → store memory
        """
        while self._running:
            try:
                await self._detect_and_handle()
            except Exception as e:
                logger.error(f"Anomaly detection error: {e}")
            await asyncio.sleep(300)  # 5 minutes

    async def _detect_and_handle(self):
        skill = self.skills.get_skill("sales-anomaly-detection")
        if not skill or "detector" not in skill.scripts:
            return
        detector = skill.scripts["detector"]

        # ── Step 1: 获取真实数据 ──
        sales_1h = await self.mcp.execute("query_sales_metrics", {"time_range": "1h"})
        sales_5m = await self.mcp.execute("query_sales_metrics", {"time_range": "5m"})

        hourly_gmv = sales_1h.get("gmv", 0)
        recent_gmv = sales_5m.get("gmv", 0)
        order_count = sales_5m.get("order_count", 0)

        # ── Step 2: 计算真实偏离度 ──
        # 预期5分钟GMV = 近1小时GMV / 12
        expected_5m = hourly_gmv / 12 if hourly_gmv > 0 else 1.0
        deviation = (recent_gmv - expected_5m) / expected_5m

        # ── Step 3: 调用检测器 ──
        result = detector.classify_anomaly(deviation, zscore=0)
        if not result.get("anomaly_detected"):
            return  # 没有异常，本轮跳过

        severity = result["severity"]
        direction = result["direction"]
        dev_pct = result["deviation_pct"]

        logger.warning(
            f"[{severity}] GMV异常: {direction}{abs(dev_pct)}% "
            f"(当前5m=¥{recent_gmv:,.0f}, 预期=¥{expected_5m:,.0f})"
        )

        # ── Step 4: 构建告警 ──
        alert = {
            "type": "gmv_deviation",
            "severity": severity,
            "title": f"[{severity}] GMV {direction}{abs(dev_pct)}% — 当前¥{recent_gmv:,.0f}",
            "description": (
                f"近5分钟GMV ¥{recent_gmv:,.0f}，较近1小时均值（¥{expected_5m:,.0f}）"
                f"{direction}{abs(dev_pct)}%。近1小时总GMV ¥{hourly_gmv:,.0f}，订单量 {order_count} 笔。"
            ),
            "current_value": recent_gmv,
            "expected_value": expected_5m,
            "deviation_pct": dev_pct,
            "timestamp": now_cst().isoformat(),
        }

        # ── Step 5: 持久化 → AlertRecord 表 ──
        from app.data.warehouse import DataWarehouse
        wh = DataWarehouse()
        wh._gen = self._gen
        wh._streams = self._streams
        alert_id = await wh.save_alert(alert)

        # ── Step 6: 推送通知 ──
        await self._push_notification(alert, sales_1h)

        # ── Step 7: 存入长期记忆 ──
        memory_content = (
            f"{now_cst().strftime('%Y-%m-%d %H:%M')} GMV异常 [{severity}]: "
            f"近5分钟GMV ¥{recent_gmv:,.0f}，{direction}{abs(dev_pct)}%。"
            f"近1小时总GMV ¥{hourly_gmv:,.0f}，订单量 {order_count} 笔。"
        )
        await self.memory.store(memory_content, {
            "type": "anomaly_analysis",
            "severity": severity,
            "deviation_pct": dev_pct,
            "alert_id": alert_id,
        })

        if alert_id:
            logger.info(f"Anomaly closed-loop complete: alert={alert_id} [{severity}]")

    # ═══════════════════════════════════════════════════════════════
    # 异常升级 (每10分钟)
    # ═══════════════════════════════════════════════════════════════

    async def _run_alert_escalation(self):
        """Periodically scan open alerts and escalate if unresolved too long.

        Escalation rules:
          P0 > 30 minutes → re-notify (critical)
          P1 > 2 hours   → upgrade to P0
          P2 > 6 hours   → upgrade to P1
        """
        while self._running:
            try:
                await self._escalate_stale_alerts()
            except Exception as e:
                logger.error(f"Alert escalation error: {e}")
            await asyncio.sleep(600)  # 10 minutes

    async def _escalate_stale_alerts(self):
        from app.data.warehouse import DataWarehouse
        wh = DataWarehouse()
        wh._gen = self._gen
        wh._streams = self._streams

        open_alerts = await wh.get_open_alerts()
        if not open_alerts:
            return

        now = datetime.now(timezone.utc)
        escalated = 0

        for alert in open_alerts:
            created_str = alert.get("created_at")
            if not created_str:
                continue
            created = datetime.fromisoformat(created_str)
            elapsed_minutes = (now - created).total_seconds() / 60
            severity = alert.get("severity", "")

            new_severity = None
            renotify = False

            if severity == "P0" and elapsed_minutes > 30:
                renotify = True
            elif severity == "P1" and elapsed_minutes > 120:
                new_severity = "P0"
                renotify = True
            elif severity == "P2" and elapsed_minutes > 360:
                new_severity = "P1"
                renotify = True

            if renotify:
                escalated += 1
                if new_severity:
                    logger.warning(
                        f"ESCALATED: alert={alert['id']} {severity}→{new_severity} "
                        f"(unresolved for {elapsed_minutes:.0f}min)"
                    )
                    # Re-push with upgraded severity
                    await self._push_notification({
                        "severity": new_severity or severity,
                        "title": f"[升级] {alert['title']}",
                        "description": (
                            f"原{alert['severity']}告警已{elapsed_minutes:.0f}分钟未处理，"
                            f"升级为{new_severity}。{alert['description']}"
                        ),
                        "deviation_pct": alert.get("deviation_pct"),
                        "current_value": alert.get("metric_value"),
                    }, {})
                else:
                    logger.info(f"Re-notify: alert={alert['id']} P0 unresolved ({elapsed_minutes:.0f}min)")

        if escalated:
            logger.info(f"Escalation round: {escalated} alerts escalated/re-notified")

    # ═══════════════════════════════════════════════════════════════
    # 竞品监控 (每5分钟)
    # ═══════════════════════════════════════════════════════════════

    async def _run_competitor_monitor(self):
        while self._running:
            try:
                skill = self.skills.get_skill("competitor-monitor")
                if not skill:
                    await asyncio.sleep(300)
                    continue

                competitor_data = await self.mcp.execute("query_competitor_prices", {})
                entries = competitor_data.get("competitor_data", [])
                if entries:
                    logger.debug(f"Competitor check: {len(entries)} records")

                    # Detect undercutting (>10% below our price)
                    for entry in entries:
                        our_price = float(entry.get("our_price", 0))
                        comp_prices = entry.get("competitor_prices", [])
                        if not comp_prices or our_price == 0:
                            continue
                        min_comp = min(p["price"] for p in comp_prices)
                        diff_pct = (min_comp - our_price) / our_price * 100
                        if diff_pct < -10:  # Competitor is >10% cheaper
                            logger.warning(
                                f"Price disadvantage: {entry.get('product_name')} "
                                f"(ours=¥{our_price}, lowest_comp=¥{min_comp}, diff={diff_pct:.1f}%)"
                            )

            except Exception as e:
                logger.error(f"Competitor monitor error: {e}")
            await asyncio.sleep(300)

    # ═══════════════════════════════════════════════════════════════
    # 库存检查 (每30分钟)
    # ═══════════════════════════════════════════════════════════════

    async def _run_inventory_check(self):
        while self._running:
            try:
                inventory = await self.mcp.execute("query_inventory", {"alert_only": True})
                alerts = [i for i in inventory.get("inventory", []) if i.get("alert")]
                if alerts:
                    logger.warning(f"Inventory alerts: {len(alerts)} products need attention")
                    for item in alerts:
                        logger.info(
                            f"  {item['product_id']}: {item['quantity']} units [{item['alert']}]"
                        )

                    # Store low-stock alerts to DB
                    from app.data.warehouse import DataWarehouse
                    wh = DataWarehouse()
                    wh._gen = self._gen
                    wh._streams = self._streams
                    for item in alerts:
                        await wh.save_alert({
                            "type": "low_stock",
                            "severity": "P1" if item["quantity"] < 10 else "P2",
                            "title": f"库存预警: {item['product_id']}",
                            "description": f"{item['product_id']} 库存仅剩 {item['quantity']} 件",
                            "current_value": item["quantity"],
                        })

            except Exception as e:
                logger.error(f"Inventory check error: {e}")
            await asyncio.sleep(1800)  # 30 minutes

    # ═══════════════════════════════════════════════════════════════
    # 通知推送 (飞书 / 钉钉)
    # ═══════════════════════════════════════════════════════════════

    async def _push_notification(self, alert: dict, sales_data: dict) -> None:
        """Push alert to configured notification channels (Feishu/DingTalk).

        Templates are loaded from skills/smart_alert/resources/templates.json.
        """
        # Load templates
        templates = _load_alert_templates()
        if not templates:
            return

        severity = alert.get("severity", "P1")
        alert_type = alert.get("type", "gmv_deviation")

        # Pick template
        type_templates = templates.get("alert_templates", {}).get(alert_type, {})
        template = type_templates.get(severity) or type_templates.get("P1", "")
        if not template:
            return

        # Fill template
        message = template.format(
            timestamp=alert.get("timestamp", now_cst().strftime("%Y-%m-%d %H:%M")),
            deviation_pct=alert.get("deviation_pct", 0),
            current_value=alert.get("current_value", 0),
            expected_value=alert.get("expected_value", 0),
            possible_causes="需进一步排查数据",
            recommendation="请查看 Dashboard 实时大屏",
        )

        # Push to channels
        channels = templates.get("notification_channels", {})
        await _push_feishu(channels.get("feishu", {}), message)
        await _push_dingtalk(channels.get("dingtalk", {}), message)


# ═══════════════════════════════════════════════════════════════════
# Module-level helpers
# ═══════════════════════════════════════════════════════════════════

def _load_alert_templates() -> Optional[dict]:
    """Load alert templates from smart-alert skill resources."""
    try:
        templates_path = (
            Path(__file__).resolve().parent.parent
            / "skills" / "smart_alert" / "resources" / "templates.json"
        )
        if templates_path.exists():
            return json.loads(templates_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load alert templates: {e}")
    return None


async def _push_feishu(channel_config: dict, message: str):
    """Send alert to Feishu bot."""
    if not channel_config.get("enabled"):
        return
    webhook = channel_config.get("webhook_url", "")
    if not webhook or "{your-hook-id}" in webhook:
        logger.debug("Feishu webhook not configured, skip push")
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                webhook,
                json={"msg_type": "text", "content": {"text": message}},
            )
            if resp.status_code == 200:
                logger.info("Feishu notification sent")
            else:
                logger.warning(f"Feishu push failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Feishu push error: {e}")


async def _push_dingtalk(channel_config: dict, message: str):
    """Send alert to DingTalk bot."""
    if not channel_config.get("enabled"):
        return
    webhook = channel_config.get("webhook_url", "")
    if not webhook or "{your-token}" in webhook:
        logger.debug("DingTalk webhook not configured, skip push")
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                webhook,
                json={"msgtype": "text", "text": {"content": message}},
            )
            if resp.status_code == 200:
                logger.info("DingTalk notification sent")
            else:
                logger.warning(f"DingTalk push failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"DingTalk push error: {e}")
