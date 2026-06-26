"""DAIOS system configuration."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DAIOSConfig:
    simulation_tick_interval: float = 2.0
    max_agents: int = 20
    kernel_port: int = 8470
    dashboard_port: int = 8471
    data_dir: str = field(default_factory=lambda: os.path.join(os.path.dirname(__file__), "..", "data"))
    memory_persistence: bool = True
    agent_retirement_idle_ticks: int = 10
    agent_cooldown_ticks: int = 2
    log_level: str = "INFO"
    enable_exploration: bool = True
    enable_growth: bool = True
    simulation_world_seed: int = 42
    resource_discovery_rate: float = 0.3
    economy_inflation_rate: float = 0.02
    max_research_goals: int = 5
    hypothesis_confidence_threshold: float = 0.6
    cloudflare_enabled: bool = False
    docker_enabled: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            simulation_tick_interval=float(os.getenv("DAIOS_TICK_INTERVAL", "2.0")),
            max_agents=int(os.getenv("DAIOS_MAX_AGENTS", "20")),
            kernel_port=int(os.getenv("DAIOS_KERNEL_PORT", "8470")),
            dashboard_port=int(os.getenv("DAIOS_DASHBOARD_PORT", "8471")),
            log_level=os.getenv("DAIOS_LOG_LEVEL", "INFO"),
            enable_exploration=os.getenv("DAIOS_EXPLORATION", "true").lower() == "true",
            enable_growth=os.getenv("DAIOS_GROWTH", "true").lower() == "true",
            simulation_world_seed=int(os.getenv("DAIOS_WORLD_SEED", "42")),
            cloudflare_enabled=os.getenv("DAIOS_CLOUDFLARE", "false").lower() == "true",
        )
