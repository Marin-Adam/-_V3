"""A2A (Agent-to-Agent) HTTP Client — V3.0 multi-agent communication.

Features:
  - JSON-RPC 2.0 over HTTP (same style as MCP)
  - Timeout isolation (configurable per call)
  - Retry with exponential backoff
  - Circuit breaker (consecutive failures → open circuit)
  - Graceful degradation (return neutral fallback on failure)
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


@dataclass
class CircuitState:
    """Per-agent circuit breaker state."""
    failures: int = 0
    last_failure_time: float = 0.0
    open_until: float = 0.0  # circuit open until this timestamp
    state: str = "closed"    # closed | open | half_open

    COOLDOWN_SEC: float = 30.0  # how long circuit stays open


class A2AClient:
    """HTTP client for A2A agent communication.

    Usage:
        client = A2AClient("http://localhost:8010")
        result = await client.call("execute", {"sql": "SELECT ..."})
    """

    def __init__(self, base_url: str, agent_name: str = "unknown"):
        self.base_url = base_url.rstrip("/")
        self.agent_name = agent_name
        self.timeout = settings.A2A_TIMEOUT
        self.max_retries = settings.A2A_RETRY
        self.circuit = CircuitState()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout + 1.0),
                limits=httpx.Limits(max_keepalive_connections=5),
            )
        return self._client

    async def call(self, method: str, params: dict = None,
                   fallback: any = None) -> dict:
        """Call an A2A agent method.

        Returns:
            result dict, or fallback on failure (never throws).
        """
        # Circuit breaker check
        if self.circuit.state == "open":
            if time.monotonic() < self.circuit.open_until:
                logger.warning(f"A2A [{self.agent_name}]: circuit OPEN, returning fallback")
                return self._fallback_result(method, fallback)
            # Try half-open
            self.circuit.state = "half_open"
            logger.info(f"A2A [{self.agent_name}]: circuit half-open, probing...")

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": str(int(time.time() * 1000)),
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                client = await self._get_client()
                resp = await client.post(
                    f"{self.base_url}/a2a",
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

                # Success → reset circuit
                self.circuit.failures = 0
                self.circuit.state = "closed"
                return data.get("result", {})

            except asyncio.TimeoutError:
                last_error = f"timeout ({self.timeout}s)"
                logger.warning(f"A2A [{self.agent_name}]: {last_error} (attempt {attempt + 1})")
            except httpx.ConnectError:
                last_error = "connection refused"
                logger.warning(f"A2A [{self.agent_name}]: {last_error}")
                break  # don't retry connection errors
            except Exception as e:
                last_error = str(e)[:100]
                logger.warning(f"A2A [{self.agent_name}]: {last_error} (attempt {attempt + 1})")

            if attempt < self.max_retries:
                await asyncio.sleep(0.3 * (2 ** attempt))

        # ── Failure: update circuit breaker ──────────────────────
        self.circuit.failures += 1
        self.circuit.last_failure_time = time.monotonic()

        if self.circuit.failures >= settings.A2A_CIRCUIT_BREAK_THRESHOLD:
            self.circuit.state = "open"
            self.circuit.open_until = time.monotonic() + CircuitState.COOLDOWN_SEC
            logger.warning(
                f"A2A [{self.agent_name}]: circuit OPEN "
                f"({self.circuit.failures} failures, cooldown {CircuitState.COOLDOWN_SEC}s)"
            )

        return self._fallback_result(method, fallback, error=last_error)

    def _fallback_result(self, method: str, fallback: any = None,
                         error: str = "") -> dict:
        """Generate a neutral fallback result."""
        if fallback is not None:
            return fallback if isinstance(fallback, dict) else {"data": fallback}
        return {
            "data": None,
            "fallback": True,
            "error": error or "agent unavailable",
            "agent": self.agent_name,
        }

    async def health(self) -> bool:
        """Check if agent is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# ── A2A Client Factory ────────────────────────────────────────────

class A2AClientFactory:
    """Creates and caches A2A clients for each agent."""

    _clients: dict[str, A2AClient] = {}

    @classmethod
    def get(cls, agent_name: str, url: str = None) -> A2AClient:
        if agent_name not in cls._clients:
            url_map = {
                "data": settings.DATA_AGENT_URL,
                "analyze": settings.ANALYZE_AGENT_URL,
                "sentiment": settings.SENTIMENT_AGENT_URL,
                "report": settings.REPORT_AGENT_URL,
            }
            base_url = url or url_map.get(agent_name, f"http://localhost:8000")
            cls._clients[agent_name] = A2AClient(base_url, agent_name)
        return cls._clients[agent_name]
