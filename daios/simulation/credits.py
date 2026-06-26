"""Virtual Resource Credits — compute, research, and build credits for agent economy."""

from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class CreditBalance:
    compute: float = 1000.0
    research: float = 500.0
    build: float = 800.0
    total_earned: float = 0.0
    total_spent: float = 0.0


CREDIT_COSTS = {
    "research_discovery": {"research": 10, "compute": 5},
    "task_execution": {"compute": 15, "build": 10},
    "hypothesis_verification": {"research": 5, "compute": 8},
    "knowledge_synthesis": {"compute": 8},
    "audit_review": {"compute": 5},
    "deployment": {"build": 20, "compute": 10},
    "documentation": {"build": 5},
}


class CreditSystem:
    def __init__(self):
        self._balances: Dict[str, CreditBalance] = {}
        self._pool = CreditBalance()

    def register_agent(self, agent_id: str, initial_compute: float = 200.0,
                       initial_research: float = 100.0, initial_build: float = 150.0) -> None:
        if agent_id not in self._balances:
            self._balances[agent_id] = CreditBalance(
                compute=initial_compute, research=initial_research,
                build=initial_build,
            )

    def spend(self, agent_id: str, action: str) -> bool:
        costs = CREDIT_COSTS.get(action)
        if not costs:
            return True
        bal = self._balances.get(agent_id)
        if not bal:
            return False
        for credit_type, amount in costs.items():
            current = getattr(bal, credit_type, 0)
            if current < amount:
                return False
        for credit_type, amount in costs.items():
            setattr(bal, credit_type, getattr(bal, credit_type, 0) - amount)
            bal.total_spent += amount
            setattr(self._pool, credit_type, getattr(self._pool, credit_type, 0) - amount)
        return True

    def earn(self, agent_id: str, compute: float = 0, research: float = 0,
             build: float = 0) -> None:
        bal = self._balances.get(agent_id)
        if not bal:
            return
        bal.compute += compute
        bal.research += research
        bal.build += build
        earned = compute + research + build
        bal.total_earned += earned
        self._pool.compute += compute
        self._pool.research += research
        self._pool.build += build

    def get_balance(self, agent_id: str) -> Optional[Dict[str, float]]:
        bal = self._balances.get(agent_id)
        if not bal:
            return None
        return {
            "compute": round(bal.compute, 1),
            "research": round(bal.research, 1),
            "build": round(bal.build, 1),
        }

    def can_afford(self, agent_id: str, action: str) -> bool:
        costs = CREDIT_COSTS.get(action)
        if not costs:
            return True
        bal = self._balances.get(agent_id)
        if not bal:
            return False
        return all(
            getattr(bal, credit_type, 0) >= amount
            for credit_type, amount in costs.items()
        )

    def daily_allowance(self, agent_id: str) -> None:
        self.earn(agent_id, compute=50, research=25, build=30)

    def summary(self) -> Dict[str, Any]:
        total_compute = sum(b.compute for b in self._balances.values())
        total_research = sum(b.research for b in self._balances.values())
        total_build = sum(b.build for b in self._balances.values())
        total_earned = sum(b.total_earned for b in self._balances.values())
        total_spent = sum(b.total_spent for b in self._balances.values())
        return {
            "agents_with_credits": len(self._balances),
            "total_compute": round(total_compute, 1),
            "total_research": round(total_research, 1),
            "total_build": round(total_build, 1),
            "total_earned": round(total_earned, 1),
            "total_spent": round(total_spent, 1),
            "pool_compute": round(self._pool.compute, 1),
        }
