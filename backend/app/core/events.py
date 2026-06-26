"""SSE event manager for real-time data streaming."""

import asyncio
from typing import AsyncGenerator


class SSEManager:
    """Publish/subscribe for Server-Sent Events."""

    def __init__(self):
        self._channels: dict[str, list[asyncio.Queue]] = {}

    async def subscribe(self, channel: str) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        if channel not in self._channels:
            self._channels[channel] = []
        self._channels[channel].append(queue)
        try:
            while True:
                data = await queue.get()
                if data is None:  # sentinel
                    break
                yield f"data: {data}\n\n"
        finally:
            self._channels[channel].remove(queue)
            if not self._channels[channel]:
                del self._channels[channel]

    async def publish(self, channel: str, data: str):
        if channel in self._channels:
            for queue in self._channels[channel]:
                await queue.put(data)

    async def close_channel(self, channel: str):
        if channel in self._channels:
            for queue in self._channels[channel]:
                await queue.put(None)


sse_manager = SSEManager()
