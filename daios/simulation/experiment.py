"""Experiment Environment — test new ideas, simulate outcomes, compare strategies."""

import random
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class Experiment:
    id: str
    name: str
    hypothesis: str
    parameters: Dict[str, Any]
    status: str
    results: Optional[Dict[str, Any]] = None
    tick_started: int = 0
    tick_completed: int = 0
    agent_id: str = ""
    tags: List[str] = field(default_factory=list)


class ExperimentEnvironment:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._experiments: List[Experiment] = []
        self._max_experiments: int = 100

    def propose(self, name: str, hypothesis: str, parameters: Dict[str, Any],
                agent_id: str = "", tags: Optional[List[str]] = None) -> str:
        eid = f"exp-{name.lower().replace(' ', '_')[:24]}-{int(time.time()%10000)}"
        experiment = Experiment(
            id=eid, name=name, hypothesis=hypothesis,
            parameters=parameters, status="proposed",
            tick_started=0, agent_id=agent_id, tags=tags or [],
        )
        self._experiments.append(experiment)
        return eid

    def start(self, experiment_id: str, tick: int) -> bool:
        for exp in self._experiments:
            if exp.id == experiment_id and exp.status == "proposed":
                exp.status = "running"
                exp.tick_started = tick
                return True
        return False

    def complete(self, experiment_id: str, tick: int) -> Optional[Dict[str, Any]]:
        for exp in self._experiments:
            if exp.id == experiment_id and exp.status == "running":
                results = self._simulate_outcome(exp.parameters)
                exp.results = results
                exp.status = "completed"
                exp.tick_completed = tick
                return results
        return None

    def _simulate_outcome(self, params: Dict) -> Dict[str, Any]:
        base_success = params.get("base_success_rate", 0.5)
        iterations = params.get("iterations", 100)
        complexity = params.get("complexity", 1.0)
        successes = 0
        for _ in range(iterations):
            if random.random() < base_success / complexity:
                successes += 1
        success_rate = successes / iterations
        return {
            "success_rate": round(success_rate, 3),
            "iterations": iterations,
            "confidence": round(abs(success_rate - base_success) * 2, 2),
            "recommendation": "proceed" if success_rate > 0.6 else "revise",
        }

    def compare_strategies(self, strategy_a: str, strategy_b: str,
                           params: Dict) -> Dict[str, Any]:
        results_a = self._simulate_outcome({**params, "base_success_rate": 0.6})
        results_b = self._simulate_outcome({**params, "base_success_rate": 0.5})
        return {
            "strategy_a": {"name": strategy_a, **results_a},
            "strategy_b": {"name": strategy_b, **results_b},
            "recommendation": strategy_a if results_a["success_rate"] > results_b["success_rate"] else strategy_b,
            "confidence_delta": round(abs(results_a["success_rate"] - results_b["success_rate"]), 3),
        }

    def get_running(self) -> List[Experiment]:
        return [e for e in self._experiments if e.status == "running"]

    def get_completed(self) -> List[Experiment]:
        return [e for e in self._experiments if e.status == "completed"]

    def summary(self) -> Dict[str, Any]:
        total = len(self._experiments)
        running = len(self.get_running())
        completed = len(self.get_completed())
        proposed = sum(1 for e in self._experiments if e.status == "proposed")
        return {
            "total": total,
            "running": running,
            "completed": completed,
            "proposed": proposed,
            "recent_completed": [
                {"name": e.name, "success_rate": e.results.get("success_rate", 0) if e.results else 0}
                for e in self._experiments if e.status == "completed"
            ][-5:],
        }

    def save(self, path: Optional[str] = None) -> str:
        path = path or str(self.data_dir / "experiments.json")
        Path(path).write_text(json.dumps({
            "experiments": [
                {"id": e.id, "name": e.name, "hypothesis": e.hypothesis,
                 "status": e.status, "results": e.results,
                 "tick_started": e.tick_started, "tick_completed": e.tick_completed}
                for e in self._experiments
            ]
        }, indent=2))
        return path

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        for ed in data.get("experiments", []):
            self._experiments.append(Experiment(**ed))
