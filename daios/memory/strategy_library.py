"""Strategy Library — stores effective approaches and reusable workflows, recommends improvements."""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class Strategy:
    id: str
    name: str
    category: str
    description: str
    steps: List[str]
    success_rate: float = 0.0
    usage_count: int = 0
    agent_type: str = ""
    tags: List[str] = field(default_factory=list)
    tick_created: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Workflow:
    id: str
    name: str
    steps: List[Dict[str, Any]]
    estimated_duration: int = 10
    success_rate: float = 0.0
    usage_count: int = 0
    tags: List[str] = field(default_factory=list)


class StrategyLibrary:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._strategies: Dict[str, Strategy] = {}
        self._workflows: Dict[str, Workflow] = {}

        self._seed_strategies()

    def _seed_strategies(self) -> None:
        seeds = [
            Strategy("strat-research", "Systematic Literature Review", "research",
                     "Investigate a topic by gathering data, forming hypotheses, and validating",
                     ["Define topic scope", "Gather data from sources",
                      "Formulate hypotheses", "Test against observations", "Document findings"],
                     success_rate=0.7, agent_type="research",
                     tags=["research", "discovery"]),
            Strategy("strat-planning", "Hierarchical Task Decomposition", "planning",
                     "Break complex goals into manageable subtasks with dependencies",
                     ["Define top-level goal", "Identify sub-goals",
                      "Order by dependency", "Assign priority levels", "Dispatch to agents"],
                     success_rate=0.8, agent_type="planner",
                     tags=["planning", "organization"]),
            Strategy("strat-build", "Iterative Construction with Validation", "building",
                     "Build artifacts incrementally with quality checks at each stage",
                     ["Parse requirements", "Design solution", "Implement core",
                      "Add tests", "Validate output", "Document"],
                     success_rate=0.75, agent_type="builder",
                     tags=["building", "quality"]),
            Strategy("strat-audit", "Multi-Layer Quality Review", "auditing",
                     "Review outputs at multiple levels: correctness, efficiency, security",
                     ["Check functional correctness", "Evaluate performance",
                      "Identify risks", "Suggest improvements", "Generate report"],
                     success_rate=0.85, agent_type="auditor",
                     tags=["audit", "quality"]),
            Strategy("strat-memory", "Pattern-Based Knowledge Synthesis", "memory",
                     "Identify recurring patterns in observations and synthesize knowledge",
                     ["Collect recent observations", "Cluster by topic",
                      "Identify recurring patterns", "Cross-reference with knowledge graph",
                      "Store synthesized insights"],
                     success_rate=0.7, agent_type="memory",
                     tags=["memory", "synthesis"]),
        ]
        for s in seeds:
            self._strategies[s.id] = s

        seed_workflows = [
            Workflow("wf-discovery", "Discovery Lifecycle",
                     [{"agent": "research", "action": "investigate topic"},
                      {"agent": "memory", "action": "store observation"},
                      {"agent": "research", "action": "form hypothesis"},
                      {"agent": "auditor", "action": "validate hypothesis"},
                      {"agent": "memory", "action": "update knowledge graph"}],
                     estimated_duration=15, success_rate=0.7,
                     tags=["discovery", "research"]),
            Workflow("wf-task-exec", "Task Execution Pipeline",
                     [{"agent": "planner", "action": "decompose goal"},
                      {"agent": "builder", "action": "execute task"},
                      {"agent": "auditor", "action": "review output"},
                      {"agent": "memory", "action": "record in task history"}],
                     estimated_duration=10, success_rate=0.8,
                     tags=["execution", "task"]),
        ]
        for wf in seed_workflows:
            self._workflows[wf.id] = wf

    def add_strategy(self, name: str, category: str, description: str,
                     steps: List[str], agent_type: str = "",
                     tags: Optional[List[str]] = None, tick: int = 0) -> str:
        sid = f"strat-{name.lower().replace(' ', '_')[:32]}"
        self._strategies[sid] = Strategy(
            id=sid, name=name, category=category, description=description,
            steps=steps, agent_type=agent_type, tags=tags or [category],
            tick_created=tick,
        )
        return sid

    def record_usage(self, strategy_id: str, success: bool) -> None:
        strat = self._strategies.get(strategy_id)
        if not strat:
            return
        strat.usage_count += 1
        total = strat.usage_count
        current_rate = strat.success_rate * (total - 1) / total
        strat.success_rate = current_rate + (1.0 / total if success else 0.0)

    def get_best_for_agent(self, agent_type: str, min_usage: int = 0) -> List[Strategy]:
        candidates = [s for s in self._strategies.values()
                      if s.agent_type == agent_type and s.usage_count >= min_usage]
        return sorted(candidates, key=lambda s: s.success_rate, reverse=True)

    def recommend(self, context: str) -> List[Dict[str, Any]]:
        ctx = context.lower()
        scored = []
        for s in self._strategies.values():
            score = 0
            if ctx in s.name.lower() or ctx in s.category.lower():
                score += 3
            if any(ctx in t.lower() for t in s.tags):
                score += 2
            score += s.success_rate * 2
            scored.append({"id": s.id, "name": s.name, "score": round(score, 1),
                           "success_rate": s.success_rate, "usage": s.usage_count})
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:5]

    def add_workflow(self, name: str, steps: List[Dict], tags: Optional[List] = None) -> str:
        wid = f"wf-{name.lower().replace(' ', '_')[:32]}"
        self._workflows[wid] = Workflow(id=wid, name=name, steps=steps, tags=tags or [])
        return wid

    def summary(self) -> Dict[str, Any]:
        return {
            "strategies": len(self._strategies),
            "workflows": len(self._workflows),
            "most_used": sorted(
                [{"name": s.name, "category": s.category, "usage": s.usage_count,
                  "success_rate": round(s.success_rate, 2)}
                 for s in self._strategies.values()],
                key=lambda x: x["usage"], reverse=True
            )[:5],
            "best_performing": sorted(
                [{"name": s.name, "category": s.category, "success_rate": round(s.success_rate, 2)}
                 for s in self._strategies.values() if s.usage_count > 0],
                key=lambda x: x["success_rate"], reverse=True
            )[:5],
        }

    def save(self, path: Optional[str] = None) -> str:
        path = path or str(self.data_dir / "strategy_library.json")
        Path(path).write_text(json.dumps({
            "strategies": {k: asdict(v) for k, v in self._strategies.items()},
            "workflows": {k: asdict(v) for k, v in self._workflows.items()},
        }, indent=2))
        return path

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        self._strategies = {k: Strategy(**v) for k, v in data.get("strategies", {}).items()}
        self._workflows = {k: Workflow(**v) for k, v in data.get("workflows", {}).items()}
