"""Builder Agent — executes tasks, builds artifacts, implements solutions."""

import logging
import random
from typing import Dict, Any, Optional
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.builder")


class BuilderAgent(BaseAgent):
    agent_type = "builder"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "construction"
        self._built_artifacts: list = []
        self._current_task: Optional[dict] = None

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(1.0)
            return
        if not self.is_active:
            return
        self.consume_energy(3.0)
        self._status = "building"
        await self._process_one_message()
        if self._current_task:
            result = await self._execute_task(self._current_task)
            if result:
                self._built_artifacts.append(result)
                await self.send_observe({"type": "artifact_built", "task": self._current_task["id"],
                                          "artifact": result})
                self._task_count += 1
            self._current_task = None
        elif random.random() < 0.2:
            improvement = await self._self_improve()
            if improvement:
                await self.send_learn({"type": "self_improvement", "detail": improvement})
        self._cooldown_ticks = random.randint(1, 3)
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            if cmd == "execute_task" and not self._current_task:
                self._current_task = msg.content.get("params", {}).get("task")
            elif cmd == "artifacts":
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "built": len(self._built_artifacts),
                    "recent": self._built_artifacts[-5:],
                }, msg.msg_id)
                await self.send(reply)

    async def _execute_task(self, task: dict) -> Optional[Dict[str, Any]]:
        desc = task.get("description", "unknown")
        artifact_type = "analysis" if "analy" in desc.lower() else "implementation"
        return {
            "id": f"artifact-{self.agent_id}-{random.randint(1000,9999)}",
            "task_id": task.get("id", ""),
            "type": artifact_type,
            "description": f"Built: {desc[:50]}",
            "quality": round(random.uniform(0.5, 1.0), 2),
        }

    async def _self_improve(self) -> Optional[str]:
        improvements = [
            "Optimized task execution pipeline",
            "Reduced resource consumption in build process",
            "Added parallel subtask processing",
            "Improved artifact quality validation",
            "Enhanced error recovery mechanism",
        ]
        return random.choice(improvements) if random.random() < 0.5 else None
