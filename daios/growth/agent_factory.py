"""Agent Factory — creates new specialized agents only with approval, manages agent lifecycle."""

import logging
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger("daios.growth")


AGENT_TYPES = {
    "research": {"module": "daios.agents.research_agent", "class": "ResearchAgent",
                 "base_energy": 100, "description": "Investigates and discovers patterns"},
    "planner": {"module": "daios.agents.planner_agent", "class": "PlannerAgent",
                "base_energy": 90, "description": "Decomposes goals into task plans"},
    "builder": {"module": "daios.agents.builder_agent", "class": "BuilderAgent",
                "base_energy": 110, "description": "Executes tasks and builds artifacts"},
    "auditor": {"module": "daios.agents.auditor_agent", "class": "AuditorAgent",
                "base_energy": 80, "description": "Validates actions and enforces rules"},
    "memory": {"module": "daios.agents.memory_agent", "class": "MemoryAgent",
               "base_energy": 70, "description": "Manages knowledge and learning"},
    "communication": {"module": "daios.agents.communication_agent", "class": "CommunicationAgent",
                      "base_energy": 60, "description": "Routes messages and manages interfaces"},
}


class AgentFactory:
    def __init__(self, kernel):
        self._kernel = kernel
        self._creation_queue: List[Dict[str, Any]] = []
        self._pending_approvals: List[Dict[str, Any]] = []
        self._specializations_used: Dict[str, int] = {}

    def propose_new_agent(self, agent_type: str, reason: str, requested_by: str) -> Optional[str]:
        if agent_type not in AGENT_TYPES:
            logger.warning("Unknown agent type: %s", agent_type)
            return None
        spec = AGENT_TYPES[agent_type]
        proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
        proposal = {
            "id": proposal_id,
            "agent_type": agent_type,
            "reason": reason,
            "requested_by": requested_by,
            "spec": spec,
        }
        self._pending_approvals.append(proposal)
        logger.info("Agent creation proposed: %s (%s) by %s", agent_type, reason, requested_by)
        return proposal_id

    def approve_creation(self, proposal_id: str) -> Optional[str]:
        proposal = None
        for p in self._pending_approvals:
            if p["id"] == proposal_id:
                proposal = p
                break
        if not proposal:
            logger.warning("Proposal not found: %s", proposal_id)
            return None
        self._pending_approvals.remove(proposal)
        agent_id = f"{proposal['agent_type']}-{uuid.uuid4().hex[:6]}"
        self._specializations_used[proposal["agent_type"]] = \
            self._specializations_used.get(proposal["agent_type"], 0) + 1
        logger.info("Agent creation approved: %s (%s)", agent_id, proposal["agent_type"])
        return agent_id

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        return list(self._pending_approvals)

    def get_growth_report(self) -> Dict[str, Any]:
        return {
            "total_created": sum(self._specializations_used.values()),
            "specializations": dict(self._specializations_used),
            "pending_approvals": len(self._pending_approvals),
            "available_types": list(AGENT_TYPES.keys()),
        }
