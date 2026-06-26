"""Communication Agent — manages message routing, external interfaces, protocol compliance."""

import logging
import random
from typing import Dict, Any, Optional, List
from daios.agents.base_agent import BaseAgent
from daios.communication.protocol import DAIOSMessage

logger = logging.getLogger("daios.agent.communication")


class CommunicationAgent(BaseAgent):
    agent_type = "communication"

    def __init__(self, agent_id: str, kernel):
        super().__init__(agent_id, kernel)
        self._specialization = "messaging"
        self._routed_messages: int = 0
        self._external_interfaces: List[str] = ["cli", "api", "webhook"]

    async def on_tick(self) -> None:
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            self.restore_energy(0.5)
            return
        if not self.is_active:
            return
        self.consume_energy(1.0)
        self._status = "routing"
        await self._process_one_message()
        self._cooldown_ticks = 1
        self._status = "idle"

    async def on_message(self, msg: DAIOSMessage) -> None:
        if msg.msg_type == "request":
            cmd = msg.content.get("command")
            if cmd == "get_network_status":
                agents = self._kernel.get_all_agents()
                statuses = {}
                for aid, agent in agents.items():
                    s = getattr(agent, "get_status", lambda: {})()
                    statuses[aid] = s
                reply = DAIOSMessage.response(self.agent_id, msg.from_id, {
                    "agents": statuses,
                    "network_size": len(agents),
                }, msg.msg_id)
                await self.send(reply)
        elif msg.msg_type == "broadcast":
            if msg.to_id == "*":
                self._routed_messages += 1
                logger.debug("Routing broadcast from %s (%d chars)",
                             msg.from_id, len(str(msg.content)))

    def get_network_report(self) -> Dict[str, Any]:
        return {
            "total_routed": self._routed_messages,
            "active_interfaces": self._external_interfaces,
            "protocol": "DAIOS v1.0 (compact JSON)",
        }
