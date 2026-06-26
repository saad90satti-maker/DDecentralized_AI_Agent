"""Message bus — routes messages between agents and kernel."""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.bus")


class MessageBus:
    def __init__(self, kernel):
        self._kernel = kernel
        self._subscribers: Dict[str, list] = {}
        self._history: list = []
        self._max_history: int = 500

    async def send(self, msg: DAIOSMessage) -> None:
        self._history.append(msg.to_dict())
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        await self._kernel.send_message(msg.to_dict())

    async def broadcast(self, msg: DAIOSMessage) -> None:
        msg.to_id = "*"
        await self.send(msg)

    async def request(self, from_id: str, to_id: str, command: str,
                      params: Optional[Dict] = None, timeout: float = 5.0) -> Optional[Dict]:
        msg = DAIOSMessage.request(from_id, to_id, command, params)
        future: asyncio.Future = asyncio.Future()
        self._pending_responses[msg.msg_id] = future
        await self.send(msg)
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._pending_responses.pop(msg.msg_id, None)
            logger.warning("Request %s from %s to %s timed out", msg.msg_id, from_id, to_id)
            return None

    async def send_observe(self, agent_id: str, observation: Dict[str, Any]) -> None:
        await self.send(DAIOSMessage.observe(agent_id, observation))

    async def send_learn(self, agent_id: str, pattern: Dict[str, Any]) -> None:
        await self.send(DAIOSMessage.learn(agent_id, pattern))

    async def send_propose(self, agent_id: str, hypothesis: Dict[str, Any]) -> None:
        await self.send(DAIOSMessage.propose(agent_id, hypothesis))

    _pending_responses: Dict[str, asyncio.Future] = {}

    def resolve_response(self, msg: DAIOSMessage) -> None:
        future = self._pending_responses.pop(msg.in_response_to, None)
        if future and not future.done():
            future.set_result(msg.content.get("data"))

    def get_history(self, last_n: int = 20) -> list:
        return self._history[-last_n:]

    def subscribe(self, msg_type: str, callback: Callable) -> None:
        self._subscribers.setdefault(msg_type, []).append(callback)

    async def dispatch(self, msg: DAIOSMessage) -> None:
        for cb in self._subscribers.get(msg.msg_type, []):
            try:
                await cb(msg)
            except Exception as e:
                logger.error("Subscriber error for %s: %s", msg.msg_type, e)
        if msg.msg_type == "response":
            self.resolve_response(msg)
