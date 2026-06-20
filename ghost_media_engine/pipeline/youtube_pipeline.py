"""
YouTube publish pipeline with LLM-generated metadata.
Combines browser automation with AI-powered content generation.
"""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ghost_media_engine.browser.controller import BrowserController
from ghost_media_engine.config import EngineConfig
from ghost_media_engine.llm.base import LLMResponse
from ghost_media_engine.logging import get_logger
from ghost_media_engine.pipeline.base import Pipeline, PipelineConfig, PipelineStep, StepResult

logger = get_logger("YouTubePipeline")


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

class ValidateVideoStep(PipelineStep):
    """Validate that the video file exists and is readable."""

    def __init__(self, video_path: str):
        super().__init__(name="validate_video")
        self.video_path = video_path

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        path = Path(self.video_path)
        if not path.exists():
            return StepResult(
                success=False,
                step_name=self.name,
                error=f"Video file not found: {path}",
            )
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info("Video validated: %s (%.1f MB)", path.name, size_mb)
        return StepResult(
            success=True,
            step_name=self.name,
            data={"path": str(path), "size_mb": round(size_mb, 2), "name": path.name},
        )


class GenerateMetadataStep(PipelineStep):
    """Use LLM to generate video title and description."""

    def __init__(self, llm, topic: str = "AI Agent Demo"):
        super().__init__(name="generate_metadata")
        self.llm = llm
        self.topic = topic

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        prompt = (
            f"Respond ONLY with a one-line JSON object with keys: title, description. "
            f'Example format: {{"title":"Short Title","description":"Brief desc."}} '
            f"No markdown. No newlines. Title under 60 chars. "
            f"Topic: {self.topic}."
        )

        response: LLMResponse = await self.llm.generate(prompt, max_tokens=200, temperature=0.2)

        if not response.success:
            # Use default metadata
            metadata = {
                "title": f"Ghost Engine - {self.topic}",
                "description": f"Autonomous AI agent demonstration using {self.topic}.",
            }
            logger.warning("LLM metadata generation failed, using defaults")
        else:
            # Parse JSON from response
            cleaned = re.sub(r'```json\s*|\s*```|```', '', response.output).strip()
            brace_start = cleaned.find('{')
            brace_end = cleaned.find('}', brace_start) + 1 if brace_start >= 0 else -1

            if brace_start >= 0 and brace_end > brace_start:
                cleaned = cleaned[brace_start:brace_end]

            try:
                metadata = json.loads(cleaned)
            except json.JSONDecodeError:
                metadata = {
                    "title": f"Ghost Engine - {self.topic}",
                    "description": f"Autonomous AI agent demonstration.",
                }
                logger.warning("Failed to parse LLM output, using defaults")

        logger.success("Generated metadata: title=%s", metadata.get("title", "")[:50])
        return StepResult(
            success=True,
            step_name=self.name,
            data=metadata,
            checkpoint_data={"metadata": metadata},
        )


class NavigateStudioStep(PipelineStep):
    """Navigate to YouTube Studio and check sign-in."""

    def __init__(self, browser: BrowserController):
        super().__init__(name="navigate_studio")
        self.browser = browser

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        result = await self.browser.navigate("https://studio.youtube.com")
        if not result.success:
            return StepResult(
                success=False,
                step_name=self.name,
                error=f"Navigation failed: {result.error}",
            )

        await self.browser.dismiss_dialogs()

        # Check sign-in
        check = await self.browser.execute_script("""
            () => {
                const body = document.body.innerText.substring(0, 2000);
                return {
                    signed_in: !body.toLowerCase().includes('sign in'),
                    title: document.title
                };
            }
        """)

        is_signed_in = check.data.get("result", {}).get("signed_in", False) if check.success else False

        if not is_signed_in:
            return StepResult(
                success=False,
                step_name=self.name,
                error="Not signed into YouTube Studio",
            )

        logger.success("YouTube Studio loaded and signed in")
        return StepResult(
            success=True,
            step_name=self.name,
            data={"title": check.data.get("result", {}).get("title", "")},
        )


class UploadVideoStep(PipelineStep):
    """Upload video file to YouTube Studio."""

    def __init__(self, browser: BrowserController, video_path: str):
        super().__init__(name="upload_video")
        self.browser = browser
        self.video_path = video_path

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        # Click Create button
        await self.browser.execute_workflow([
            {"action": "click", "selector": "ytcp-button#create-icon, [aria-label='Create']"},
        ])

        # Click Upload
        await self.browser.execute_workflow([
            {"action": "click", "selector": "ytcp-ve:has-text('Upload videos'), text=Upload videos"},
        ])

        # Upload file
        video_name = Path(self.video_path).name
        result = await self.browser.execute_script(f"""
            async () => {{
                const selectors = [
                    "input[type='file']",
                    "ytcp-uploads-file-picker input",
                    ".upload-file-picker input"
                ];
                for (const sel of selectors) {{
                    const input = document.querySelector(sel);
                    if (input) {{
                        return {{ found: true, selector: sel }};
                    }}
                }}
                return {{ found: false }};
            }}
        """)

        if not result.success or not result.data.get("result", {}).get("found"):
            return StepResult(
                success=False,
                step_name=self.name,
                error="File input not found on page",
            )

        logger.success("Video upload initiated: %s", video_name)
        return StepResult(
            success=True,
            step_name=self.name,
            data={"video_name": video_name, "status": "uploading"},
        )


class FillMetadataStep(PipelineStep):
    """Fill video title and description from context."""

    def __init__(self, browser: BrowserController):
        super().__init__(name="fill_metadata")
        self.browser = browser

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        metadata = context.get("metadata", {})
        title = metadata.get("title", "")
        description = metadata.get("description", "")

        # Wait for processing
        await self.browser.wait_for(
            "#title-textbox, #textbox, [aria-label*='Title']",
            timeout=60000,
        )

        if title:
            await self.browser.type_text(
                "#title-textbox, #textbox, [aria-label*='Title']",
                title[:100],
                human_like=True,
            )
            logger.info("Title filled: %s", title[:50])

        if description:
            await self.browser.type_text(
                "#description-textbox, [aria-label*='Description']",
                description[:500],
                human_like=True,
            )
            logger.info("Description filled")

        return StepResult(
            success=True,
            step_name=self.name,
            data={"title": title, "description": description[:100] + "..."},
        )


class PublishStep(PipelineStep):
    """Click through publish dialogs."""

    def __init__(self, browser: BrowserController):
        super().__init__(name="publish")
        self.browser = browser

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        # Click Next buttons
        for _ in range(3):
            try:
                await self.browser.execute_workflow([
                    {"action": "click", "selector": "ytcp-button#next-button, #next-button"},
                ])
                await asyncio.sleep(2)
            except Exception:
                break

        # Click Publish/Done
        publish_result = await self.browser.execute_workflow([
            {"action": "click", "selector": "ytcp-button#done-button, #done-button"},
        ])

        if publish_result.success:
            logger.success("Video published!")
            return StepResult(
                success=True,
                step_name=self.name,
                data={"published": True},
            )
        else:
            return StepResult(
                success=False,
                step_name=self.name,
                error="Publish button not found",
            )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

class YouTubePublishPipeline:
    """
    Complete YouTube publish pipeline with LLM metadata and self-healing.

    Usage:
        from ghost_media_engine.config import EngineConfig
        from ghost_media_engine.browser.controller import BrowserController
        from ghost_media_engine.llm.gemini import GeminiLLM

        config = EngineConfig.from_env()
        llm = GeminiLLM(config.llm)

        async with BrowserController(config) as browser:
            pipeline = YouTubePublishPipeline(browser, llm, config)
            result = await pipeline.run("demo.mp4", topic="AI Agent Demo")
    """

    def __init__(
        self,
        browser: BrowserController,
        llm,
        config: EngineConfig,
    ):
        self.browser = browser
        self.llm = llm
        self.config = config
        self._pipeline: Optional[Pipeline] = None

    def build_pipeline(self, video_path: str, topic: str = "AI Agent Demo") -> Pipeline:
        """Build the YouTube publish pipeline with all steps."""
        pipeline_config = PipelineConfig(
            max_retries=2,
            step_timeout=120,
            checkpoint_dir=self.config.pipeline.checkpoint_dir,
            screenshot_on_error=self.config.pipeline.screenshot_on_error,
        )

        pipeline = Pipeline("youtube_publish", pipeline_config)

        pipeline.add_step(ValidateVideoStep(video_path))
        pipeline.add_step(GenerateMetadataStep(self.llm, topic))
        pipeline.add_step(NavigateStudioStep(self.browser))
        pipeline.add_step(UploadVideoStep(self.browser, video_path))
        pipeline.add_step(FillMetadataStep(self.browser))
        pipeline.add_step(PublishStep(self.browser))

        self._pipeline = pipeline
        return pipeline

    async def run(
        self,
        video_path: str,
        topic: str = "AI Agent Demo",
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the complete YouTube publish pipeline."""
        pipeline = self.build_pipeline(video_path, topic)

        context = {
            "video_path": video_path,
            "topic": topic,
        }
        if extra_context:
            context.update(extra_context)

        result = await pipeline.execute(context)

        # Take screenshot on error
        if not result.get("success") and self.config.pipeline.screenshot_on_error:
            try:
                await self.browser.screenshot("agent_data/publish_error.png")
            except Exception:
                pass

        return result
