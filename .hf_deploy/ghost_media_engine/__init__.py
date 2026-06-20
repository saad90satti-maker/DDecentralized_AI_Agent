"""
Ghost Media Engine - Autonomous Media Generation & Web Automation Framework
=============================================================================
Modular, async-first architecture with self-healing browser automation,
unified LLM routing, and declarative pipeline workflows.

Usage:
    from ghost_media_engine import GhostEngine
    from ghost_media_engine.config import EngineConfig

    config = EngineConfig.from_env()
    async with GhostEngine(config) as engine:
        result = await engine.run_workflow("youtube_publish", video_path="demo.mp4")
"""

__version__ = "3.0.0"
__author__ = "Ghost Engine"

from ghost_media_engine.config import EngineConfig
from ghost_media_engine.browser.controller import BrowserController

__all__ = ["EngineConfig", "BrowserController"]
