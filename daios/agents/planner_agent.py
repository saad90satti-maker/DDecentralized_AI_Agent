"""Planner Agent — decomposes goals into tasks, assigns priorities, tracks progress."""

import logging
import random
import uuid
from typing import Dict, Any, List, Optional
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.planner")


class PlannerAgent(BaseAgent):
    agent_type = "planner"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "planning"
        self._active_plans: Dict[str, dict] = {}
        self._task_queue: List[dict] = []
        self._completed_tasks: List[dict] = []

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(2.0)
        self._status = "planning"
        await self._process_one_message()
        if not self._task_queue and random.random() < 0.3:
            self._generate_plan()
        elif self._task_queue and random.random() < 0.4:
            task = self._task_queue.pop(0)
            task["assigned_to"] = self._select_agent()
            await self._dispatch_task(task)
        self._cooldown_ticks = random.randint(1, 2)
        self._status = "idle"
        self._task_count += 1

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            if cmd == "get_plans":
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "active_plans": len(self._active_plans),
                    "pending_tasks": len(self._task_queue),
                    "completed_tasks": len(self._completed_tasks),
                }, msg.msg_id)
                await self.send(reply)
        elif msg.msg_type == "broadcast":
            if "new_goal" in msg.content:
                self._decompose_goal(msg.content["new_goal"])

    def _generate_plan(self) -> None:
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        plan = {
            "id": plan_id,
            "goal": f"Research initiative alpha-{random.randint(1,50)}",
            "tasks": [
                {"id": f"t-{plan_id}-1", "description": "Gather initial data", "priority": "high"},
                {"id": f"t-{plan_id}-2", "description": "Analyze findings", "priority": "medium"},
                {"id": f"t-{plan_id}-3", "description": "Synthesize report", "priority": "low"},
            ],
            "status": "active",
        }
        self._active_plans[plan_id] = plan
        self._task_queue.extend(plan["tasks"])
        logger.info("%s created plan %s: %s", self.agent_id, plan_id, plan["goal"])

    def _decompose_goal(self, goal: str) -> None:
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        tasks = [
            {"id": f"t-{plan_id}-1", "description": f"Research: {goal}", "priority": "high"},
            {"id": f"t-{plan_id}-2", "description": f"Plan execution for: {goal}", "priority": "high"},
            {"id": f"t-{plan_id}-3", "description": f"Build solution for: {goal}", "priority": "medium"},
            {"id": f"t-{plan_id}-4", "description": f"Audit results for: {goal}", "priority": "medium"},
        ]
        self._active_plans[plan_id] = {"id": plan_id, "goal": goal, "tasks": tasks, "status": "active"}
        self._task_queue.extend(tasks)
        logger.info("%s decomposed goal '%s' into %d tasks", self.agent_id, goal, len(tasks))

    def _select_agent(self) -> str:
        agents = self._kernel.get_all_agents()
        if not agents:
            return "kernel"
        return random.choice(list(agents.keys()))

    async def _dispatch_task(self, task: dict) -> None:
        msg = DAIOSMessage.request(self.agent_id, task["assigned_to"], "execute_task", {
            "task": task,
        })
        await self.send(msg)
        await self.send_observe({"type": "task_dispatched", "task": task["id"],
                                  "to": task["assigned_to"]})
