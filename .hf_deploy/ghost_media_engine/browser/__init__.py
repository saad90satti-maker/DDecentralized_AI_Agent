"""Browser automation module with self-healing controller."""

from ghost_media_engine.browser.controller import BrowserController
from ghost_media_engine.browser.tasks import GmailTask, YouTubeTask, GitHubTask
from ghost_media_engine.browser.workflows import Workflow, build_youtube_publish_workflow

__all__ = ["BrowserController", "GmailTask", "YouTubeTask", "GitHubTask", "Workflow", "build_youtube_publish_workflow"]
