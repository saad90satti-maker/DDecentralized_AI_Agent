"""Knowledge Graph — connects concepts, tracks relationships, builds institutional knowledge."""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field, asdict


@dataclass
class ConceptNode:
    id: str
    name: str
    category: str
    description: str = ""
    confidence: float = 0.5
    source: str = ""
    tick_created: int = 0
    access_count: int = 0
    tags: List[str] = field(default_factory=list)


@dataclass
class RelationshipEdge:
    source_id: str
    target_id: str
    relation_type: str
    strength: float = 0.5
    evidence_count: int = 1
    tick_created: int = 0


class KnowledgeGraph:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._nodes: Dict[str, ConceptNode] = {}
        self._edges: List[RelationshipEdge] = []

    def add_concept(self, name: str, category: str, description: str = "",
                    source: str = "", tick: int = 0, tags: Optional[List[str]] = None,
                    confidence: float = 0.5) -> str:
        cid = f"concept-{name.lower().replace(' ', '_')[:32]}"
        if cid in self._nodes:
            existing = self._nodes[cid]
            existing.access_count += 1
            existing.confidence = max(existing.confidence, confidence)
            if description and not existing.description:
                existing.description = description
            return cid
        self._nodes[cid] = ConceptNode(
            id=cid, name=name, category=category, description=description,
            confidence=confidence, source=source, tick_created=tick,
            tags=tags or [category],
        )
        return cid

    def add_relationship(self, source: str, target: str, relation_type: str,
                         strength: float = 0.5, tick: int = 0) -> None:
        for edge in self._edges:
            if (edge.source_id == source and edge.target_id == target
                    and edge.relation_type == relation_type):
                edge.evidence_count += 1
                edge.strength = min(1.0, edge.strength + 0.1)
                return
        self._edges.append(RelationshipEdge(
            source_id=source, target_id=target, relation_type=relation_type,
            strength=strength, tick_created=tick,
        ))

    def get_concept(self, concept_id: str) -> Optional[ConceptNode]:
        node = self._nodes.get(concept_id)
        if node:
            node.access_count += 1
        return node

    def search_concepts(self, query: str) -> List[ConceptNode]:
        q = query.lower()
        results = []
        for node in self._nodes.values():
            if (q in node.name.lower() or q in node.description.lower()
                    or any(q in t.lower() for t in node.tags)):
                results.append(node)
        return sorted(results, key=lambda x: x.confidence, reverse=True)

    def get_related(self, concept_id: str, max_depth: int = 1) -> List[Dict[str, Any]]:
        related = []
        visited: Set[str] = {concept_id}
        queue = [(concept_id, 0)]
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for edge in self._edges:
                neighbor = None
                if edge.source_id == current and edge.target_id not in visited:
                    neighbor = edge.target_id
                elif edge.target_id == current and edge.source_id not in visited:
                    neighbor = edge.source_id
                if neighbor:
                    visited.add(neighbor)
                    node = self._nodes.get(neighbor)
                    if node:
                        related.append({
                            "concept": node.name,
                            "relation": edge.relation_type,
                            "strength": edge.strength,
                            "depth": depth + 1,
                        })
                    queue.append((neighbor, depth + 1))
        return related

    def get_graph_summary(self) -> Dict[str, Any]:
        categories: Dict[str, int] = {}
        for node in self._nodes.values():
            categories[node.category] = categories.get(node.category, 0) + 1
        relation_counts: Dict[str, int] = {}
        for edge in self._edges:
            relation_counts[edge.relation_type] = relation_counts.get(edge.relation_type, 0) + 1
        return {
            "total_concepts": len(self._nodes),
            "total_relationships": len(self._edges),
            "categories": categories,
            "relation_types": relation_counts,
            "top_concepts": sorted(
                [{"name": n.name, "category": n.category, "confidence": n.confidence, "access": n.access_count}
                 for n in self._nodes.values()],
                key=lambda x: x["access"], reverse=True
            )[:10],
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "nodes": {k: asdict(v) for k, v in self._nodes.items()},
            "edges": [asdict(e) for e in self._edges],
        }

    def save(self, path: Optional[str] = None) -> str:
        path = path or str(self.data_dir / "knowledge_graph.json")
        Path(path).write_text(json.dumps(self.snapshot(), indent=2))
        return path

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text())
        self._nodes = {k: ConceptNode(**v) for k, v in data.get("nodes", {}).items()}
        self._edges = [RelationshipEdge(**e) for e in data.get("edges", [])]
