"""
Ghost Media Engine - Main Entry Point
======================================
Unified CLI with signal handling, graceful shutdown, and task dispatch.

Usage:
    python -m ghost_media_engine gmail --count 5
    python -m ghost_media_engine youtube --check
    python -m ghost_media_engine youtube --upload demo.mp4 --title "My Video"
    python -m ghost_media_engine github --check
    python -m ghost_media_engine pipeline --video demo.mp4 --topic "AI Demo"
    python -m ghost_media_engine health
"""

import argparse
import asyncio
import signal
import sys
import time
from typing import Optional

from ghost_media_engine.config import EngineConfig
from ghost_media_engine.logging import init_logging, get_logger, set_correlation_id


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

class GracefulShutdown:
    """Handle SIGINT/SIGTERM for clean browser closure."""

    def __init__(self):
        self.should_exit = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def install(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                signal.signal(sig, self._handle_signal_sync)

    def _handle_signal(self) -> None:
        self.should_exit = True
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _handle_signal_sync(self, signum, frame) -> None:
        self.should_exit = True


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_gmail(config: EngineConfig, args) -> None:
    """Fetch emails from Gmail."""
    from ghost_media_engine.browser.controller import BrowserController
    from ghost_media_engine.browser.tasks import GmailTask

    logger = get_logger("CMD")

    async with BrowserController(config) as browser:
        task = GmailTask(browser)
        result = await task.fetch_emails(count=args.count)

        if result.success:
            logger.success("Gmail fetch completed")
            emails = result.data.get("emails", [])
            for i, email in enumerate(emails, 1):
                print(f"  {i}. From: {email.get('sender', 'unknown')}")
                print(f"     Subject: {email.get('subject', 'no subject')}")
        else:
            logger.error("Gmail fetch failed: %s", result.error)
            sys.exit(1)


async def cmd_youtube(config: EngineConfig, args) -> None:
    """YouTube operations."""
    from ghost_media_engine.browser.controller import BrowserController
    from ghost_media_engine.browser.tasks import YouTubeTask

    logger = get_logger("CMD")

    async with BrowserController(config) as browser:
        task = YouTubeTask(browser)

        if args.check:
            result = await task.check_sign_in()
            if result.success:
                status = result.data.get("status", "UNKNOWN")
                print(f"  YouTube status: {status}")
                if status != "ACTIVE":
                    sys.exit(1)
            else:
                logger.error("YouTube check failed: %s", result.error)
                sys.exit(1)

        if args.upload:
            result = await task.upload_video(
                video_path=args.upload,
                title=args.title or "",
                description=args.description or "",
            )
            if result.success:
                logger.success("YouTube upload initiated")
            else:
                logger.error("YouTube upload failed: %s", result.error)
                sys.exit(1)


async def cmd_github(config: EngineConfig, args) -> None:
    """GitHub operations."""
    from ghost_media_engine.browser.controller import BrowserController
    from ghost_media_engine.browser.tasks import GitHubTask

    logger = get_logger("CMD")

    async with BrowserController(config) as browser:
        task = GitHubTask(browser)
        result = await task.check_session()

        if result.success:
            status = result.data.get("status", "UNKNOWN")
            print(f"  GitHub status: {status}")
            if status != "ACTIVE":
                sys.exit(1)
        else:
            logger.error("GitHub check failed: %s", result.error)
            sys.exit(1)


async def cmd_pipeline(config: EngineConfig, args) -> None:
    """Run YouTube publish pipeline."""
    from ghost_media_engine.browser.controller import BrowserController
    from ghost_media_engine.llm.gemini import GeminiLLM
    from ghost_media_engine.pipeline.youtube_pipeline import YouTubePublishPipeline

    logger = get_logger("CMD")

    llm = GeminiLLM(config.llm)

    async with BrowserController(config) as browser:
        pipeline = YouTubePublishPipeline(browser, llm, config)
        result = await pipeline.run(
            video_path=args.video,
            topic=args.topic or "AI Agent Demo",
        )

        print("\n" + "=" * 60)
        print("  PIPELINE RESULT")
        print("=" * 60)
        print(f"  Success: {result.get('success', False)}")
        print(f"  Steps: {result.get('steps_completed', 0)}/{result.get('steps_total', 0)}")
        print(f"  Duration: {result.get('duration_ms', 0):.0f}ms")
        print("=" * 60)

        for step_result in result.get("results", []):
            icon = "[OK]" if step_result.get("success") else "[!]"
            print(f"  {icon} {step_result.get('step', 'unknown')}")

        print("=" * 60)

        if not result.get("success"):
            sys.exit(1)


async def cmd_health(config: EngineConfig) -> None:
    """Check health of all configured services."""
    from ghost_media_engine.llm.gemini import GeminiLLM
    from ghost_media_engine.llm.hermes import HermesLLM

    logger = get_logger("CMD")

    print("\n" + "=" * 60)
    print("  GHOST MEDIA ENGINE - HEALTH CHECK")
    print("=" * 60)

    # Config warnings
    warnings = config.validate()
    if warnings:
        print("\n  Configuration Warnings:")
        for w in warnings:
            print(f"    [!] {w}")

    # Gemini
    print("\n  LLM Backends:")
    if config.llm.gemini_api_key:
        gemini = GeminiLLM(config.llm)
        ok = await gemini.health_check()
        print(f"    Gemini: {'OK' if ok else 'UNREACHABLE'}")
    else:
        print(f"    Gemini: NOT CONFIGURED (set GEMINI_API_KEY)")

    # Hermes
    hermes = HermesLLM(config.llm)
    ok = await hermes.health_check()
    print(f"    Hermes: {'OK' if ok else 'UNREACHABLE'} (at {config.llm.hermes_url})")

    # Browser
    print("\n  Browser:")
    print(f"    Profile: {config.browser.user_data_dir}")
    print(f"    Headless: {config.browser.headless}")

    # Email
    print("\n  Email:")
    if config.email.user:
        print(f"    Gmail: CONFIGURED ({config.email.user})")
    else:
        print(f"    Gmail: NOT CONFIGURED (set GMAIL_USER)")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ghost_media_engine",
        description="Ghost Media Engine - Autonomous Media Generation & Web Automation",
    )
    parser.add_argument("--env", help="Path to .env file", default=None)
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Gmail
    gmail_parser = subparsers.add_parser("gmail", help="Gmail operations")
    gmail_parser.add_argument("--count", type=int, default=5, help="Number of emails to fetch")

    # YouTube
    youtube_parser = subparsers.add_parser("youtube", help="YouTube operations")
    youtube_parser.add_argument("--check", action="store_true", help="Check sign-in status")
    youtube_parser.add_argument("--upload", metavar="VIDEO_PATH", help="Upload a video")
    youtube_parser.add_argument("--title", help="Video title")
    youtube_parser.add_argument("--description", help="Video description")

    # GitHub
    github_parser = subparsers.add_parser("github", help="GitHub operations")
    github_parser.add_argument("--check", action="store_true", help="Check session status")

    # Pipeline
    pipeline_parser = subparsers.add_parser("pipeline", help="Run publish pipeline")
    pipeline_parser.add_argument("--video", required=True, help="Path to video file")
    pipeline_parser.add_argument("--topic", help="Topic for LLM metadata generation")

    # Health
    subparsers.add_parser("health", help="Health check")

    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()

    # Initialize logging
    init_logging(
        level="DEBUG" if args.verbose else "INFO",
        log_dir=None,
    )

    # Load config
    config = EngineConfig.from_env(args.env)

    # Install graceful shutdown
    shutdown = GracefulShutdown()
    try:
        loop = asyncio.get_running_loop()
        shutdown.install(loop)
    except RuntimeError:
        pass

    # Set correlation ID for request tracing
    cid = set_correlation_id()

    logger = get_logger("Main")
    logger.info("Ghost Media Engine v3.0 starting (correlation_id=%s)", cid)

    # Dispatch command
    try:
        if args.command == "gmail":
            await cmd_gmail(config, args)
        elif args.command == "youtube":
            await cmd_youtube(config, args)
        elif args.command == "github":
            await cmd_github(config, args)
        elif args.command == "pipeline":
            await cmd_pipeline(config, args)
        elif args.command == "health":
            await cmd_health(config)
        else:
            print("No command specified. Use --help for usage.")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)


def main() -> None:
    """Entry point for console_scripts."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
