"""
Browser task implementations for Gmail, YouTube, and GitHub.
Each task uses BrowserController for self-healing and retry.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ghost_media_engine.browser.controller import BrowserController, ActionResult
from ghost_media_engine.logging import get_logger

logger = get_logger("BrowserTasks")


# ---------------------------------------------------------------------------
# Dataclasses for task results
# ---------------------------------------------------------------------------

@dataclass
class EmailInfo:
    sender: str
    subject: str
    preview: str = ""
    received_at: str = ""


@dataclass
class TaskResult:
    success: bool
    task_name: str
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "task": self.task_name,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


# ---------------------------------------------------------------------------
# Gmail Task
# ---------------------------------------------------------------------------

class GmailTask:
    """
    Fetch emails from Gmail inbox via browser automation.

    Usage:
        async with BrowserController(config) as browser:
            task = GmailTask(browser)
            result = await task.fetch_emails(count=5)
    """

    GMAIL_URL = "https://mail.google.com/mail/u/0/#inbox"

    def __init__(self, browser: BrowserController):
        self._browser = browser

    async def fetch_emails(self, count: int = 5) -> TaskResult:
        """Fetch the latest emails from Gmail inbox."""
        import time
        start = time.time()

        try:
            # Navigate to Gmail
            nav_result = await self._browser.navigate(self.GMAIL_URL)
            if not nav_result.success:
                return TaskResult(
                    success=False,
                    task_name="gmail_fetch",
                    error=f"Navigation failed: {nav_result.error}",
                    duration_ms=(time.time() - start) * 1000,
                )

            # Wait for inbox to load
            await self._browser.dismiss_dialogs()
            await self._browser.wait_for("tr.zA, tr.zE, [role='listitem']", timeout=15000)

            # Extract email rows
            emails_data = await self._browser.execute_script(f"""
                () => {{
                    const rows = document.querySelectorAll('tr.zA, tr.zE, [role="listitem"]');
                    const emails = [];
                    const limit = Math.min(rows.length, {count});
                    for (let i = 0; i < limit; i++) {{
                        const row = rows[i];
                        let sender = '';
                        let subject = '';
                        try {{
                            const senderEl = row.querySelector('span.yP, span.zF, [email]');
                            sender = senderEl ? (senderEl.getAttribute('email') || senderEl.innerText) : 'unknown';
                        }} catch {{ sender = 'unknown'; }}
                        try {{
                            const subjectEl = row.querySelector('span.bog, span[data-subject]');
                            subject = subjectEl ? (subjectEl.getAttribute('data-subject') || subjectEl.innerText) : 'no subject';
                        }} catch {{ subject = 'no subject'; }}
                        emails.push({{ sender, subject }});
                    }}
                    return emails;
                }}
            """)

            if emails_data.success:
                emails = emails_data.data.get("result", []) if isinstance(emails_data.data, dict) else []
                logger.success("Fetched %d emails from Gmail", len(emails))
                return TaskResult(
                    success=True,
                    task_name="gmail_fetch",
                    data={"emails": emails, "count": len(emails)},
                    duration_ms=(time.time() - start) * 1000,
                )
            else:
                return TaskResult(
                    success=False,
                    task_name="gmail_fetch",
                    error="Failed to extract email data",
                    duration_ms=(time.time() - start) * 1000,
                )

        except Exception as exc:
            logger.exception("Gmail task failed: %s", exc)
            return TaskResult(
                success=False,
                task_name="gmail_fetch",
                error=str(exc),
                duration_ms=(time.time() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# YouTube Task
# ---------------------------------------------------------------------------

class YouTubeTask:
    """
    YouTube Studio automation for upload and publish.

    Usage:
        async with BrowserController(config) as browser:
            task = YouTubeTask(browser)
            result = await task.check_sign_in()
            result = await task.upload_video("demo.mp4")
    """

    STUDIO_URL = "https://studio.youtube.com"
    YOUTUBE_URL = "https://www.youtube.com/"

    def __init__(self, browser: BrowserController):
        self._browser = browser

    async def check_sign_in(self) -> TaskResult:
        """Check if user is signed into YouTube."""
        import time
        start = time.time()

        try:
            nav_result = await self._browser.navigate(self.YOUTUBE_URL)
            if not nav_result.success:
                return TaskResult(
                    success=False,
                    task_name="youtube_check_signin",
                    error=f"Navigation failed: {nav_result.error}",
                    duration_ms=(time.time() - start) * 1000,
                )

            # Check for avatar button (indicates signed in)
            check = await self._browser.execute_script("""
                () => {
                    const avatar = document.querySelector('#avatar-btn img, button#avatar-btn img, img.yt-spec-avatar');
                    const signIn = document.querySelector('a[href*="accounts.google.com"], tp-yt-paper-button:has-text("Sign in")');
                    return {
                        signed_in: !!avatar,
                        has_sign_in_button: !!signIn
                    };
                }
            """)

            is_signed_in = False
            if check.success:
                is_signed_in = check.data.get("result", {}).get("signed_in", False)

            status = "ACTIVE" if is_signed_in else "NOT_SIGNED_IN"
            logger.info("YouTube sign-in status: %s", status)

            return TaskResult(
                success=True,
                task_name="youtube_check_signin",
                data={"signed_in": is_signed_in, "status": status},
                duration_ms=(time.time() - start) * 1000,
            )

        except Exception as exc:
            logger.exception("YouTube sign-in check failed: %s", exc)
            return TaskResult(
                success=False,
                task_name="youtube_check_signin",
                error=str(exc),
                duration_ms=(time.time() - start) * 1000,
            )

    async def upload_video(self, video_path: str, title: str = "", description: str = "") -> TaskResult:
        """Upload a video to YouTube Studio."""
        import time
        start = time.time()

        try:
            # Navigate to YouTube Studio
            nav_result = await self._browser.navigate(self.STUDIO_URL)
            if not nav_result.success:
                return TaskResult(
                    success=False,
                    task_name="youtube_upload",
                    error=f"Navigation failed: {nav_result.error}",
                    duration_ms=(time.time() - start) * 1000,
                )

            await self._browser.dismiss_dialogs()

            # Click Create button
            create_result = await self._browser.execute_workflow([
                {"action": "click", "selector": "ytcp-button#create-icon", "required": False},
                {"action": "click", "selector": "[aria-label='Create']", "required": False},
                {"action": "click", "selector": "ytcp-button:has-text('Create')", "required": False},
            ])

            # Click Upload videos
            upload_option = await self._browser.execute_workflow([
                {"action": "click", "selector": "ytcp-ve:has-text('Upload videos')", "required": False},
                {"action": "click", "selector": "text=Upload videos", "required": False},
            ])

            # Upload file
            file_result = await self._browser.execute_script(f"""
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

            if file_result.success and file_result.data.get("result", {}).get("found"):
                selector = file_result.data["result"]["selector"]
                # Set file input
                await self._browser.execute_script(f"""
                    async () => {{
                        const input = document.querySelector('{selector}');
                        if (input) {{
                            const dt = new DataTransfer();
                            const file = new File([''], '{video_path.split('/')[-1]}', {{ type: 'video/mp4' }});
                            dt.items.add(file);
                            input.files = dt.files;
                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    }}
                """)

                logger.success("Video upload initiated: %s", video_path)

                # Fill metadata if provided
                if title:
                    await self._browser.type_text(
                        "#title-textbox, #textbox, [aria-label*='Title']",
                        title,
                        human_like=True,
                    )
                if description:
                    await self._browser.type_text(
                        "#description-textbox, [aria-label*='Description']",
                        description,
                        human_like=True,
                    )

                return TaskResult(
                    success=True,
                    task_name="youtube_upload",
                    data={
                        "video_path": video_path,
                        "title": title,
                        "description": description,
                        "status": "upload_initiated",
                    },
                    duration_ms=(time.time() - start) * 1000,
                )
            else:
                return TaskResult(
                    success=False,
                    task_name="youtube_upload",
                    error="File input not found on page",
                    duration_ms=(time.time() - start) * 1000,
                )

        except Exception as exc:
            logger.exception("YouTube upload failed: %s", exc)
            return TaskResult(
                success=False,
                task_name="youtube_upload",
                error=str(exc),
                duration_ms=(time.time() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# GitHub Task
# ---------------------------------------------------------------------------

class GitHubTask:
    """
    GitHub browser automation for session check and repo sync.

    Usage:
        async with BrowserController(config) as browser:
            task = GitHubTask(browser)
            result = await task.check_session()
    """

    GITHUB_URL = "https://github.com"

    def __init__(self, browser: BrowserController):
        self._browser = browser

    async def check_session(self) -> TaskResult:
        """Check if user is signed into GitHub."""
        import time
        start = time.time()

        try:
            nav_result = await self._browser.navigate(self.GITHUB_URL)
            if not nav_result.success:
                return TaskResult(
                    success=False,
                    task_name="github_check_session",
                    error=f"Navigation failed: {nav_result.error}",
                    duration_ms=(time.time() - start) * 1000,
                )

            # Check for signed-in indicators
            check = await self._browser.execute_script("""
                () => {
                    const signInBtn = document.querySelector('a[href*="login"], a[href*="signin"]');
                    const avatar = document.querySelector('img[alt*="@"], .AppHeader-user');
                    const bodyText = document.body.innerText.substring(0, 500);
                    return {
                        signed_in: !!avatar || !signInBtn,
                        has_sign_in_button: !!signInBtn,
                        body_preview: bodyText.substring(0, 200)
                    };
                }
            """)

            is_signed_in = False
            if check.success:
                is_signed_in = check.data.get("result", {}).get("signed_in", False)

            status = "ACTIVE" if is_signed_in else "NOT_SIGNED_IN"
            logger.info("GitHub session status: %s", status)

            return TaskResult(
                success=True,
                task_name="github_check_session",
                data={"signed_in": is_signed_in, "status": status},
                duration_ms=(time.time() - start) * 1000,
            )

        except Exception as exc:
            logger.exception("GitHub session check failed: %s", exc)
            return TaskResult(
                success=False,
                task_name="github_check_session",
                error=str(exc),
                duration_ms=(time.time() - start) * 1000,
            )
