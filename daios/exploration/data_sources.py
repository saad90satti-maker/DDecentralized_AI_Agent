"""Approved data sources for agent exploration."""

from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class DataSource:
    id: str
    name: str
    category: str
    reliability: float
    access_type: str
    url: str = ""


APPROVED_SOURCES: List[DataSource] = [
    DataSource("ds1", "Agent Observation Log", "internal", 0.95, "shared_memory"),
    DataSource("ds2", "Simulation Event Feed", "internal", 0.90, "world_state"),
    DataSource("ds3", "Community Reports", "internal", 0.80, "world_communities"),
    DataSource("ds4", "Economy Indicators", "internal", 0.85, "world_economy"),
    DataSource("ds5", "Research Progress DB", "internal", 0.90, "world_research"),
    DataSource("ds6", "Peer Discovery Feed", "peer", 0.70, "agent_broadcast"),
    DataSource("ds7", "Hypothesis Registry", "internal", 0.75, "shared_memory"),
    DataSource("ds8", "Learning Pattern Store", "internal", 0.80, "shared_memory"),
]


def get_source(source_id: str) -> DataSource:
    for s in APPROVED_SOURCES:
        if s.id == source_id:
            return s
    raise ValueError(f"Unknown data source: {source_id}")


def get_sources_by_category(category: str) -> List[DataSource]:
    return [s for s in APPROVED_SOURCES if s.category == category]


def get_high_reliability_sources(min_reliability: float = 0.8) -> List[DataSource]:
    return [s for s in APPROVED_SOURCES if s.reliability >= min_reliability]
