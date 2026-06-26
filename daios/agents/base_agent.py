"""Base Agent — abstract class for all DAIOS agent types."""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from daios.communication.protocol import DAIOSMessage
from daios.kernel.kernel_node import KernelNode

logger = logging.getLogger("daios.agent")


class BaseAgent(ABC):
    agent_type: str = "base"

    def __init__(self, agent_id: str, kernel: KernelNode):
        self.agent_id = agent_id
        self._kernel = kernel
        self._bus = kernel._message_queue  # direct ref to kernel's queue
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._energy: float = 100.0
        self._status: str = "idle"
        self._task_count: int = 0
        self._observation_count: int = 0
        self._discovery_count: int = 0
        self._specialization: str = ""
        self._cooldown_ticks: int = 0

    async def send(self, msg: DAIOSMessage) -> None:
        await self._kernel.send_message(msg.to_dict())

    async def send_request(self, to_id: str, command: str, params: Optional[Dict] = None) -> None:
        msg = DAIOSMessage.request(self.agent_id, to_id, command, params)
        await self.send(msg)

    async def send_observe(self, observation: Dict[str, Any]) -> None:
        self._observation_count += 1
        await self.send(DAIOSMessage.observe(self.agent_id, observation))

    async def send_learn(self, pattern: Dict[str, Any]) -> None:
        await self.send(DAIOSMessage.learn(self.agent_id, pattern))

    async def send_propose(self, hypothesis: Dict[str, Any]) -> None:
        self._discovery_count += 1
        await self.send(DAIOSMessage.propose(self.agent_id, hypothesis))

    async def send_broadcast(self, content: Dict[str, Any], msg_type: str = "broadcast") -> None:
        await self.send(DAIOSMessage.broadcast(self.agent_id, content, msg_type))

    async def handle_message(self, msg: Dict[str, Any]) -> None:
        await self._message_queue.put(msg)

    async def _process_one_message(self) -> None:
        try:
            msg_dict = await asyncio.wait_for(self._message_queue.get(), timeout=0.5)
            msg = DAIOSMessage.from_dict(msg_dict)
            await self.on_message(msg)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error("Agent %s error processing message: %s", self.agent_id, e)

    @abstractmethod
    async def on_message(self, msg: DAIOSMessage) -> None:
        ...

    @abstractmethod
    async def on_tick(self) -> None:
        ...

    def get_status(self) -> Dict[str, Any]:
        return {
            "id": self.agent_id,
            "type": self.agent_type,
            "status": self._status,
            "specialization": self._specialization,
            "energy": round(self._energy, 1),
            "tasks_completed": self._task_count,
            "observations": self._observation_count,
            "discoveries": self._discovery_count,
        }

    def consume_energy(self, amount: float = 1.0) -> None:
        self._energy = max(0.0, self._energy - amount)

    def restore_energy(self, amount: float = 5.0) -> None:
        self._energy = min(100.0, self._energy + amount)

    @property
    def is_active(self) -> bool:
        return self._energy > 0 and self._status != "retired"

    @property
    def is_idle(self) -> bool:
        return self._status == "idle"
