"""System state management — tracks all agent states, world state, and system health."""

import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict


@dataclass
class SystemState:
    tick: int = 0
    start_time: float = field(default_factory=time.time)
    active_agents: int = 0
    total_agents_created: int = 0
    total_tasks_completed: int = 0
    total_discoveries: int = 0
    total_messages_sent: int = 0
    kernel_status: str = "initializing"
    phase: str = "bootstrap"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class StateManager:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._state = SystemState()
        self._agent_states: Dict[str, Dict[str, Any]] = {}
        self._resource_pool: Dict[str, float] = {}
        self._dirty: bool = False

    @property
    def state(self) -> SystemState:
        return self._state

    @property
    def agent_count(self) -> int:
        return len(self._agent_states)

    def register_agent(self, agent_id: str, agent_type: str) -> None:
        self._agent_states[agent_id] = {
            "id": agent_id,
            "type": agent_type,
            "status": "idle",
            "created_tick": self._state.tick,
            "last_active_tick": self._state.tick,
            "tasks_completed": 0,
            "energy": 100.0,
            "observations_count": 0,
            "discoveries_count": 0,
        }
        self._state.active_agents = len(self._agent_states)
        self._state.total_agents_created += 1
        self._dirty = True

    def unregister_agent(self, agent_id: str) -> None:
        self._agent_states.pop(agent_id, None)
        self._state.active_agents = len(self._agent_states)
        self._dirty = True

    def update_agent(self, agent_id: str, **updates) -> None:
        if agent_id in self._agent_states:
            self._agent_states[agent_id].update(updates)
            self._agent_states[agent_id]["last_active_tick"] = self._state.tick
            self._dirty = True

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agent_states.get(agent_id)

    def get_all_agents(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._agent_states)

    def get_agents_by_type(self, agent_type: str) -> List[Dict[str, Any]]:
        return [a for a in self._agent_states.values() if a["type"] == agent_type]

    def idle_agents(self, max_ticks: int) -> List[str]:
        cutoff = self._state.tick - max_ticks
        return [
            aid for aid, a in self._agent_states.items()
            if a["last_active_tick"] < cutoff
        ]

    def tick(self) -> None:
        self._state.tick += 1

    def add_error(self, error: str) -> None:
        self._state.errors.append(f"[T{self._state.tick}] {error}")
        self._dirty = True

    def add_warning(self, warning: str) -> None:
        self._state.warnings.append(f"[T{self._state.tick}] {warning}")
        self._dirty = True

    def set_resource(self, name: str, amount: float) -> None:
        self._resource_pool[name] = amount
        self._dirty = True

    def modify_resource(self, name: str, delta: float) -> Optional[float]:
        current = self._resource_pool.get(name, 0.0)
        new_val = max(0.0, current + delta)
        self._resource_pool[name] = new_val
        self._dirty = True
        return new_val

    def get_resource(self, name: str) -> float:
        return self._resource_pool.get(name, 0.0)

    def all_resources(self) -> Dict[str, float]:
        return dict(self._resource_pool)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": asdict(self._state),
            "agents": self._agent_states,
            "resources": self._resource_pool,
        }

    def save_checkpoint(self) -> str:
        path = self.data_dir / "checkpoints" / f"state_t{self._state.tick}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2))
        self._dirty = False
        return str(path)

    def load_checkpoint(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        self._state = SystemState(**data["state"])
        self._agent_states = data["agents"]
        self._resource_pool = data["resources"]
