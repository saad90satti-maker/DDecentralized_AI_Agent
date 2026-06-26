"""Simulation World — virtual environment with economy, resources, tasks, communities, research."""

import random
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from daios.kernel.config import DAIOSConfig

logger = logging.getLogger("daios.world")


@dataclass
class Community:
    id: str
    name: str
    size: int
    wealth: float
    tech_level: float
    happiness: float
    goals: List[str] = field(default_factory=list)


@dataclass
class ResearchGoal:
    id: str
    title: str
    field: str
    progress: float
    complexity: float
    contributors: List[str] = field(default_factory=list)
    completed: bool = False


class SimulationWorld:
    def __init__(self, config: DAIOSConfig):
        self.config = config
        random.seed(config.simulation_world_seed)
        self.tick: int = 0
        self.resources: Dict[str, float] = {
            "energy": 1000.0,
            "data": 500.0,
            "compute": 800.0,
            "knowledge": 200.0,
        }
        self.communities: List[Community] = self._init_communities()
        self.research_goals: List[ResearchGoal] = self._init_research()
        self.economy: Dict[str, float] = {
            "gdp": 10000.0,
            "inflation": config.economy_inflation_rate,
            "trade_volume": 5000.0,
            "innovation_index": 50.0,
        }
        self._event_log: List[str] = []

    def _init_communities(self) -> List[Community]:
        return [
            Community(id="c1", name="Alpha Valley", size=1000, wealth=50000, tech_level=3.0, happiness=0.7,
                      goals=["Build research center", "Improve energy grid"]),
            Community(id="c2", name="Beta Heights", size=750, wealth=35000, tech_level=4.0, happiness=0.8,
                      goals=["Develop AI systems", "Expand trade routes"]),
            Community(id="c3", name="Gamma Plains", size=500, wealth=20000, tech_level=2.0, happiness=0.6,
                      goals=["Establish farming co-op", "Build school"]),
        ]

    def _init_research(self) -> List[ResearchGoal]:
        return [
            ResearchGoal(id="rg1", title="Quantum Computing Breakthrough", field="physics",
                         progress=0.0, complexity=0.8),
            ResearchGoal(id="rg2", title="Sustainable Energy Solution", field="physics",
                         progress=0.0, complexity=0.6),
            ResearchGoal(id="rg3", title="Distributed Intelligence Protocol", field="computing",
                         progress=0.0, complexity=0.7),
        ]

    def tick_update(self) -> Dict[str, Any]:
        self.tick += 1
        events = []
        self._update_economy()
        self._update_communities()
        self._update_resources()
        for goal in self.research_goals:
            if not goal.completed and random.random() < 0.1:
                progress = round(random.uniform(0.01, 0.05) * self.economy["innovation_index"] / 50, 3)
                goal.progress = min(1.0, goal.progress + progress)
                if goal.progress >= 1.0:
                    goal.completed = True
                    events.append(f"Research completed: {goal.title}")
                    logger.info("World: %s", events[-1])
        if events:
            self._event_log.extend(events)
        return {
            "tick": self.tick,
            "events": events,
            "economy": dict(self.economy),
            "resources": dict(self.resources),
        }

    def _update_economy(self) -> None:
        self.economy["gdp"] *= (1 + random.uniform(-0.02, 0.05))
        self.economy["gdp"] = max(5000, self.economy["gdp"])
        self.economy["innovation_index"] *= (1 + random.uniform(-0.01, 0.03))
        self.economy["innovation_index"] = max(10, min(100, self.economy["innovation_index"]))

    def _update_communities(self) -> None:
        for c in self.communities:
            c.size += random.randint(-5, 15)
            c.size = max(100, c.size)
            c.wealth *= (1 + random.uniform(-0.03, 0.06))
            c.happiness = max(0.1, min(1.0, c.happiness + random.uniform(-0.05, 0.05)))
            if random.random() < 0.05:
                c.tech_level += 0.1

    def _update_resources(self) -> None:
        self.resources["energy"] += random.uniform(-20, 50)
        self.resources["energy"] = max(100, self.resources["energy"])
        if random.random() < self.config.resource_discovery_rate:
            self.resources["knowledge"] += random.uniform(5, 20)

    def get_available_tasks(self) -> List[Dict[str, Any]]:
        tasks = []
        for c in self.communities:
            for goal in c.goals[:2]:
                tasks.append({
                    "id": f"task-{c.id}-{random.randint(1000,9999)}",
                    "community": c.id,
                    "description": goal,
                    "reward": round(random.uniform(100, 500), 1),
                    "complexity": round(random.uniform(1, 5), 1),
                })
        return tasks

    def get_research_summary(self) -> List[Dict[str, Any]]:
        return [{"id": g.id, "title": g.title, "progress": round(g.progress, 2),
                  "completed": g.completed, "contributors": len(g.contributors)}
                for g in self.research_goals]

    def get_status(self) -> Dict[str, Any]:
        return {
            "tick": self.tick,
            "economy": {k: round(v, 1) for k, v in self.economy.items()},
            "resources": {k: round(v, 1) for k, v in self.resources.items()},
            "communities": [
                {"id": c.id, "name": c.name, "size": c.size, "happiness": round(c.happiness, 2),
                 "tech": round(c.tech_level, 1)}
                for c in self.communities
            ],
            "research": self.get_research_summary(),
            "recent_events": self._event_log[-10:],
        }
