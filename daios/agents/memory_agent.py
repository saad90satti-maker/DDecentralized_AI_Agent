"""Memory Agent — manages shared knowledge, curates observations, synthesizes learning."""

import logging
import random
from typing import Dict, Any, Optional
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage
from daios.memory.shared_memory import SharedMemory

logger = logging.getLogger("daios.agent.memory")


class MemoryAgent(BaseAgent):
    agent_type = "memory"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "knowledge_management"
        self._memory = SharedMemory(kernel.config.data_dir)
        self._processed_observations: int = 0
        self._synthesized_patterns: int = 0

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(1.5)
        self._status = "processing"
        await self._process_one_message()
        if random.random() < 0.3:
            await self._synthesize_knowledge()
        self._cooldown_ticks = 1
        self._task_count += 1
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "observe":
            self._memory.add_observation(msg.from_id, msg.content, msg.tick or 0)
            self._processed_observations += 1
        elif msg.msg_type == "learn":
            self._memory.add_learning(msg.from_id, msg.content, msg.tick or 0,
                                      confidence=msg.content.get("confidence", 0.5))
            self._synthesized_patterns += 1
        elif msg.msg_type == "request":
            cmd = msg.content.get("command")
            params = msg.content.get("params", {})
            data = None
            if cmd == "get_knowledge":
                data = self._memory.get_knowledge(params.get("key", ""))
            elif cmd == "search_knowledge":
                entries = self._memory.search_knowledge(params.get("query", ""))
                data = [{"key": e.key, "value": e.value, "confidence": e.confidence} for e in entries]
            elif cmd == "get_observations":
                data = [o.observation for o in self._memory.get_observations(
                    params.get("agent_id"), params.get("last_n", 20))]
            elif cmd == "get_patterns":
                data = [{"pattern": l.pattern, "confidence": l.confidence}
                        for l in self._memory.get_learning()]
            elif cmd == "memory_stats":
                data = self._memory.snapshot()
            if data is not None:
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, data, msg.msg_id)
                await self.send(reply)

    async def _synthesize_knowledge(self) -> None:
        recent = self._memory.get_observations(last_n=20)
        if len(recent) < 3:
            return
        topic = random.choice(["physics", "biology", "economics", "computing", "social"])
        pattern = {
            "type": "synthesized_pattern",
            "topic": topic,
            "pattern": f"Observed correlation in {topic} across {len(recent)} data points",
            "confidence": round(random.uniform(0.3, 0.8), 2),
            "source_count": len(recent),
        }
        self._memory.add_learning("memory_agent", pattern, self._kernel.state_mgr.state.tick,
                                  confidence=pattern["confidence"])
        self._memory.store_knowledge(f"pattern_{topic}_{self._kernel.state_mgr.state.tick}",
                                      pattern, "memory_agent", self._kernel.state_mgr.state.tick,
                                      confidence=pattern["confidence"],
                                      tags=[topic, "synthesized"])
        logger.info("%s synthesized %s pattern (conf=%.2f)", self.agent_id, topic, pattern["confidence"])
