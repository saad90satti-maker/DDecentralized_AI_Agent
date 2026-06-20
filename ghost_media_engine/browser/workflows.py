"""
Declarative workflow orchestrator for multi-step browser automation.
Steps are defined as config dicts, not imperative code.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ghost_media_engine.browser.controller import BrowserController, ActionResult
from ghost_media_engine.logging import get_logger

logger = get_logger("Workflows")


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    name: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    required: bool = True
    on_failure: str = "abort"  # abort, skip, retry
    max_retries: int = 2


@dataclass
class WorkflowResult:
    """Result of a complete workflow execution."""
    success: bool
    workflow_name: str
    steps_completed: int
    steps_total: int
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "workflow": self.workflow_name,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "step_results": self.step_results,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


class Workflow:
    """
    Declarative workflow orchestrator.

    Usage:
        workflow = Workflow("youtube_publish", steps=[
            WorkflowStep(name="navigate", action="goto", params={"url": "https://studio.youtube.com"}),
            WorkflowStep(name="dismiss_dialogs", action="dismiss"),
            WorkflowStep(name="click_create", action="click", params={"selector": "[aria-label='Create']"}),
        ])
        result = await workflow.execute(browser)
    """

    def __init__(self, name: str, steps: List[WorkflowStep]):
        self.name = name
        self.steps = steps

    async def execute(self, browser: BrowserController) -> WorkflowResult:
        """Execute all workflow steps sequentially."""
        start = time.time()
        completed = 0
        step_results = []
        failed = False

        logger.info("Starting workflow '%s' (%d steps)", self.name, len(self.steps))

        for i, step in enumerate(self.steps):
            logger.info("Step %d/%d: %s", i + 1, len(self.steps), step.name)

            # Execute with retries if configured
            step_success = False
            last_error = None

            for attempt in range(1, step.max_retries + 1):
                try:
                    result = await self._execute_step(browser, step)
                    step_success = result.success
                    last_error = result.error

                    step_results.append({
                        "step": i,
                        "name": step.name,
                        "action": step.action,
                        "status": "success" if result.success else "failed",
                        "error": result.error,
                        "attempts": attempt,
                    })

                    if result.success:
                        logger.success("Step %d completed: %s", i + 1, step.name)
                        completed += 1
                        break
                    else:
                        logger.warning(
                            "Step %d failed (attempt %d/%d): %s",
                            i + 1, attempt, step.max_retries, result.error,
                        )

                except Exception as exc:
                    last_error = str(exc)
                    logger.warning(
                        "Step %d exception (attempt %d/%d): %s",
                        i + 1, attempt, step.max_retries, exc,
                    )

            # Handle failure based on on_failure policy
            if not step_success:
                if step.on_failure == "abort":
                    logger.error("Workflow aborted at step %d: %s", i + 1, step.name)
                    failed = True
                    break
                elif step.on_failure == "skip":
                    logger.warning("Skipping failed step: %s", step.name)
                    step_results.append({
                        "step": i, "name": step.name,
                        "action": step.action, "status": "skipped",
                        "error": last_error,
                    })
                else:
                    step_results.append({
                        "step": i, "name": step.name,
                        "action": step.action, "status": "failed",
                        "error": last_error,
                    })

        duration = (time.time() - start) * 1000
        success = not failed and completed == len(self.steps)

        if success:
            logger.success(
                "Workflow '%s' completed: %d/%d steps in %.1fs",
                self.name, completed, len(self.steps), duration / 1000,
            )
        else:
            logger.error(
                "Workflow '%s' failed: %d/%d steps completed in %.1fs",
                self.name, completed, len(self.steps), duration / 1000,
            )

        return WorkflowResult(
            success=success,
            workflow_name=self.name,
            steps_completed=completed,
            steps_total=len(self.steps),
            step_results=step_results,
            error=last_error if not success else None,
            duration_ms=duration,
        )

    async def _execute_step(
        self, browser: BrowserController, step: WorkflowStep,
    ) -> ActionResult:
        """Execute a single workflow step."""
        action = step.action
        params = step.params

        if action == "goto":
            return await browser.navigate(params["url"], **{k: v for k, v in params.items() if k != "url"})
        elif action == "click":
            return await browser.click(params["selector"], **{k: v for k, v in params.items() if k != "selector"})
        elif action == "fill":
            return await browser.type_text(
                params["selector"], params["value"],
                clear_first=params.get("clear_first", True),
                human_like=params.get("human_like", True),
            )
        elif action == "fill_form":
            return await browser.fill_form(params["fields"])
        elif action == "wait_for":
            return await browser.wait_for(params["selector"], params.get("timeout"))
        elif action == "scroll":
            return await browser.scroll_to_bottom()
        elif action == "screenshot":
            return await browser.screenshot(params.get("path", "workflow_screenshot.png"))
        elif action == "script":
            return await browser.execute_script(params["script"])
        elif action == "get_text":
            return await browser.get_text(params["selector"])
        elif action == "dismiss":
            return await browser.dismiss_dialogs()
        elif action == "analyze":
            return await browser.analyze_page()
        elif action == "custom":
            func = params.get("func")
            if func and callable(func):
                result = await func(browser)
                return result if isinstance(result, ActionResult) else ActionResult(
                    success=True, data=result,
                )
            return ActionResult(success=False, error="No callable func provided for custom step")
        else:
            return ActionResult(success=False, error=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Pre-built workflows
# ---------------------------------------------------------------------------

def build_youtube_publish_workflow(video_path: str, title: str = "", description: str = "") -> Workflow:
    """Build a standard YouTube publish workflow."""
    steps = [
        WorkflowStep(
            name="navigate_studio",
            action="goto",
            params={"url": "https://studio.youtube.com"},
        ),
        WorkflowStep(
            name="dismiss_dialogs",
            action="dismiss",
            required=False,
            on_failure="skip",
        ),
        WorkflowStep(
            name="click_create",
            action="click",
            params={"selector": "ytcp-button#create-icon, [aria-label='Create']"},
            on_failure="retry",
            max_retries=3,
        ),
        WorkflowStep(
            name="click_upload",
            action="click",
            params={"selector": "ytcp-ve:has-text('Upload videos'), text=Upload videos"},
            on_failure="retry",
            max_retries=3,
        ),
        WorkflowStep(
            name="upload_file",
            action="script",
            params={"script": f"""
                async () => {{
                    const selectors = ["input[type='file']", "ytcp-uploads-file-picker input"];
                    for (const sel of selectors) {{
                        const input = document.querySelector(sel);
                        if (input) {{
                            const dt = new DataTransfer();
                            const file = new File([''], '{video_path.split('/')[-1]}', {{ type: 'video/mp4' }});
                            dt.items.add(file);
                            input.files = dt.files;
                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return {{ success: true, selector: sel }};
                        }}
                    }}
                    return {{ success: false }};
                }}
            """},
        ),
    ]

    # Add metadata steps if provided
    if title:
        steps.append(WorkflowStep(
            name="fill_title",
            action="fill",
            params={
                "selector": "#title-textbox, #textbox, [aria-label*='Title']",
                "value": title,
            },
            required=False,
            on_failure="skip",
        ))

    if description:
        steps.append(WorkflowStep(
            name="fill_description",
            action="fill",
            params={
                "selector": "#description-textbox, [aria-label*='Description']",
                "value": description,
            },
            required=False,
            on_failure="skip",
        ))

    return Workflow("youtube_publish", steps)


def build_gmail_check_workflow(count: int = 5) -> Workflow:
    """Build a Gmail inbox check workflow."""
    return Workflow("gmail_check", [
        WorkflowStep(
            name="navigate_gmail",
            action="goto",
            params={"url": "https://mail.google.com/mail/u/0/#inbox"},
        ),
        WorkflowStep(
            name="dismiss_dialogs",
            action="dismiss",
            required=False,
            on_failure="skip",
        ),
        WorkflowStep(
            name="wait_for_inbox",
            action="wait_for",
            params={"selector": "tr.zA, tr.zE, [role='listitem']", "timeout": 15000},
            on_failure="retry",
            max_retries=2,
        ),
        WorkflowStep(
            name="analyze_inbox",
            action="analyze",
            required=False,
            on_failure="skip",
        ),
    ])


def build_github_check_workflow() -> Workflow:
    """Build a GitHub session check workflow."""
    return Workflow("github_check", [
        WorkflowStep(
            name="navigate_github",
            action="goto",
            params={"url": "https://github.com"},
        ),
        WorkflowStep(
            name="analyze_page",
            action="analyze",
            required=False,
            on_failure="skip",
        ),
    ])
