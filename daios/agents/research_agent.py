"""Research Agent — investigates data sources, generates hypotheses, shares discoveries."""

import logging
import random
from typing import Dict, Any, Optional
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.research")


class ResearchAgent(BaseAgent):
    agent_type = "research"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "exploration"
        self._discoveries: list = []
        self._active_hypotheses: list = []
        self._exploration_focus: Optional[str] = None

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(2.0)
        self._status = "researching"
        await self._process_one_message()
        topic = self._exploration_focus or random.choice(self._get_research_topics())
        discovery = await self._discover(topic)
        if discovery:
            self._discoveries.append(discovery)
            await self.send_propose(discovery)
            await self.send_observe({"type": "discovery", "topic": topic, "finding": discovery})
            logger.info("%s discovered: %s", self.agent_id, discovery.get("title", "unknown"))
        self._cooldown_ticks = random.randint(1, 3)
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            if cmd == "explore":
                self._exploration_focus = msg.content.get("params", {}).get("topic")
            elif cmd == "findings":
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "discoveries": self._discoveries[-10:],
                    "hypotheses": self._active_hypotheses[-5:],
                }, msg.msg_id)
                await self.send(reply)
        elif msg.msg_type == "broadcast":
            if "new_research_topic" in msg.content:
                self._exploration_focus = msg.content["new_research_topic"]

    async def _discover(self, topic: str) -> Optional[Dict[str, Any]]:
        discoveries_map = {
            "physics": lambda: {"title": f"Particle interaction pattern #{random.randint(100,999)}",
                                "field": "physics", "confidence": round(random.uniform(0.3, 0.9), 2)},
            "biology": lambda: {"title": f"Gene expression pathway #{random.randint(100,999)}",
                                "field": "biology", "confidence": round(random.uniform(0.3, 0.9), 2)},
            "economics": lambda: {"title": f"Market equilibrium model v{random.randint(1,5)}",
                                  "field": "economics", "confidence": round(random.uniform(0.3, 0.9), 2)},
            "computing": lambda: {"title": f"Distributed algorithm optimization #{random.randint(1,50)}",
                                  "field": "computing", "confidence": round(random.uniform(0.3, 0.9), 2)},
            "social": lambda: {"title": f"Community cooperation pattern #{random.randint(1,50)}",
                               "field": "social_dynamics", "confidence": round(random.uniform(0.3, 0.9), 2)},
        }
        generator = discoveries_map.get(topic, discoveries_map["computing"])
        result = generator()
        if random.random() < 0.7:
            return result
        return None

    def _get_research_topics(self) -> list:
        return ["physics", "biology", "economics", "computing", "social"]
