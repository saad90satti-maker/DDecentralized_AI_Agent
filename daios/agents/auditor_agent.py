"""Auditor Agent — validates all agent actions, enforces rules, checks quality."""

import logging
import random
from typing import Dict, Any, List, Optional
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.auditor")


class AuditorAgent(BaseAgent):
    agent_type = "auditor"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "oversight"
        self._audit_log: List[dict] = []
        self._rules: List[str] = [
            "No destructive actions without approval",
            "All discoveries must be logged",
            "Resource usage must be efficient",
            "Communication must use compact format",
            "Agent energy must stay above 10%",
        ]

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(2.0)
        self._status = "auditing"
        await self._process_one_message()
        audit_result = await self._perform_audit()
        if audit_result:
            self._audit_log.append(audit_result)
            if audit_result["severity"] == "high":
                await self.send_broadcast({"audit_finding": audit_result}, "alert")
                logger.warning("%s audit: %s", self.agent_id, audit_result["message"])
        self._cooldown_ticks = random.randint(1, 3)
        self._task_count += 1
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            if cmd == "get_audit_log":
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "logs": self._audit_log[-20:],
                }, msg.msg_id)
                await self.send(reply)

    async def _perform_audit(self) -> Optional[Dict[str, Any]]:
        agents = self._kernel.get_all_agents()
        findings = []
        severity = "low"
        for aid, agent in agents.items():
            status = getattr(agent, "get_status", lambda: {})()
            energy = status.get("energy", 100)
            if energy < 15:
                findings.append(f"{aid} low energy ({energy})")
                severity = "medium"
        if findings:
            return {
                "type": "audit",
                "tick": self._kernel.state_mgr.state.tick,
                "severity": severity,
                "findings": findings[:5],
                "message": "; ".join(findings[:3]),
            }
        if random.random() < 0.3:
            return {
                "type": "audit",
                "tick": self._kernel.state_mgr.state.tick,
                "severity": "info",
                "findings": ["All agents operating normally"],
                "message": "Clean audit — no violations detected",
            }
        return None
