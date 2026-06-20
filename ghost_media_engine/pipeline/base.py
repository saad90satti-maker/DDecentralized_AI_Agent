"""
Abstract pipeline step and pipeline executor with checkpoint/resume support.
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ghost_media_engine.logging import get_logger

logger = get_logger("Pipeline")


@dataclass
class StepResult:
    """Result of a single pipeline step execution."""
    success: bool
    step_name: str
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    checkpoint_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "step": self.step_name,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


class PipelineStep(ABC):
    """
    Abstract base class for pipeline steps.

    Each step implements:
    - execute(context) -> StepResult
    - rollback(context) (optional)
    """

    def __init__(self, name: str, required: bool = True):
        self.name = name
        self.required = required

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> StepResult:
        """Execute the step. Context contains shared state between steps."""
        ...

    async def rollback(self, context: Dict[str, Any]) -> None:
        """Rollback the step if needed (optional)."""
        pass

    def __repr__(self) -> str:
        return f"<Step:{self.name} required={self.required}>"


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution."""
    max_retries: int = 2
    step_timeout: int = 120
    checkpoint_dir: str = "agent_data/checkpoints"
    screenshot_on_error: bool = True


class Pipeline:
    """
    Pipeline executor with sequential step execution and checkpointing.

    Usage:
        pipeline = Pipeline("youtube_publish", config)
        pipeline.add_step(ValidateVideoStep("demo.mp4"))
        pipeline.add_step(UploadVideoStep())
        pipeline.add_step(PublishStep())
        result = await pipeline.execute({"video_path": "demo.mp4"})
    """

    def __init__(self, name: str, config: Optional[PipelineConfig] = None):
        self.name = name
        self.config = config or PipelineConfig()
        self._steps: List[PipelineStep] = []
        self._results: List[StepResult] = []

    def add_step(self, step: PipelineStep) -> "Pipeline":
        """Add a step to the pipeline (chainable)."""
        self._steps.append(step)
        return self

    async def execute(self, initial_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute all pipeline steps sequentially with checkpointing."""
        start = time.time()
        context = initial_context or {}
        context["pipeline_name"] = self.name
        context["pipeline_start"] = start

        self._results = []
        completed_steps = []

        logger.info("Starting pipeline '%s' (%d steps)", self.name, len(self._steps))

        # Load checkpoint if exists
        checkpoint = self._load_checkpoint()
        if checkpoint:
            logger.info("Resuming from checkpoint: step %d", checkpoint.get("next_step", 0))
            context.update(checkpoint.get("context", {}))
            start_idx = checkpoint.get("next_step", 0)
        else:
            start_idx = 0

        for i, step in enumerate(self._steps[start_idx:], start=start_idx):
            logger.info("Step %d/%d: %s", i + 1, len(self._steps), step.name)

            # Execute with retries
            step_success = False
            last_error = None

            for attempt in range(1, self.config.max_retries + 1):
                try:
                    result = await self._execute_step_with_timeout(step, context)
                    step_success = result.success
                    last_error = result.error

                    if result.success:
                        self._results.append(result)
                        completed_steps.append(i)

                        # Update context with step data
                        if result.data:
                            context[step.name] = result.data
                        if result.checkpoint_data:
                            context.update(result.checkpoint_data)

                        # Save checkpoint
                        self._save_checkpoint(i + 1, context)
                        logger.success("Step %d completed: %s", i + 1, step.name)
                        break
                    else:
                        logger.warning(
                            "Step %d failed (attempt %d/%d): %s",
                            i + 1, attempt, self.config.max_retries, result.error,
                        )

                except Exception as exc:
                    last_error = str(exc)
                    logger.warning(
                        "Step %d exception (attempt %d/%d): %s",
                        i + 1, attempt, self.config.max_retries, exc,
                    )

            # Handle step failure
            if not step_success:
                if step.required:
                    logger.error("Pipeline aborted at required step: %s", step.name)
                    self._results.append(StepResult(
                        success=False,
                        step_name=step.name,
                        error=last_error,
                    ))
                    break
                else:
                    logger.warning("Skipping optional step: %s", step.name)
                    self._results.append(StepResult(
                        success=False,
                        step_name=step.name,
                        error=f"Skipped: {last_error}",
                    ))

        duration = (time.time() - start) * 1000
        all_success = all(r.success for r in self._results if r.step_name in [s.name for s in self._steps if s.required])

        # Cleanup checkpoint on success
        if all_success:
            self._cleanup_checkpoint()

        result = {
            "pipeline": self.name,
            "success": all_success,
            "steps_completed": len(completed_steps),
            "steps_total": len(self._steps),
            "results": [r.to_dict() for r in self._results],
            "duration_ms": round(duration, 2),
            "context": {k: v for k, v in context.items() if not k.startswith("_")},
        }

        if all_success:
            logger.success("Pipeline '%s' completed in %.1fs", self.name, duration / 1000)
        else:
            logger.error("Pipeline '%s' failed in %.1fs", self.name, duration / 1000)

        return result

    async def _execute_step_with_timeout(
        self, step: PipelineStep, context: Dict[str, Any],
    ) -> StepResult:
        """Execute a step with timeout."""
        import asyncio
        start = time.time()
        try:
            result = await asyncio.wait_for(
                step.execute(context),
                timeout=self.config.step_timeout,
            )
            result.duration_ms = (time.time() - start) * 1000
            return result
        except asyncio.TimeoutError:
            return StepResult(
                success=False,
                step_name=step.name,
                error=f"Step timed out after {self.config.step_timeout}s",
                duration_ms=(time.time() - start) * 1000,
            )

    def _checkpoint_path(self) -> Path:
        checkpoint_dir = Path(self.config.checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir / f"{self.name}_checkpoint.json"

    def _save_checkpoint(self, next_step: int, context: Dict[str, Any]) -> None:
        try:
            checkpoint = {
                "pipeline": self.name,
                "next_step": next_step,
                "context": {k: str(v) if not isinstance(v, (str, int, float, bool, list, dict)) else v
                           for k, v in context.items() if not k.startswith("_")},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._checkpoint_path().write_text(
                json.dumps(checkpoint, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Failed to save checkpoint: %s", exc)

    def _load_checkpoint(self) -> Optional[Dict[str, Any]]:
        path = self._checkpoint_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _cleanup_checkpoint(self) -> None:
        try:
            path = self._checkpoint_path()
            if path.exists():
                path.unlink()
        except Exception:
            pass
