"""
Centralized configuration with python-dotenv and typed dataclasses.
All secrets loaded from environment only - never hardcoded.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class BrowserConfig:
    """Browser automation settings."""
    headless: bool = False
    user_data_dir: str = str(Path.home() / ".ghost_browser_profile")
    viewport_width: int = 1280
    viewport_height: int = 720
    locale: str = "en-US"
    timezone_id: str = "America/Los_Angeles"
    block_resources: bool = True
    max_pages: int = 5
    navigation_timeout_ms: int = 30000
    action_timeout_ms: int = 15000

    @property
    def viewport(self) -> dict:
        return {"width": self.viewport_width, "height": self.viewport_height}


@dataclass(frozen=True)
class LLMConfig:
    """LLM backend settings - all from env vars."""
    gemini_api_key: str = ""
    gemini_model: str = "models/gemini-2.5-flash"
    hermes_url: str = "http://localhost:11434"
    hermes_model: str = "llama3.2:1b"
    hermes_timeout: int = 15
    gemini_timeout: int = 30
    max_retries: int = 3
    rate_limit_rpm: int = 15  # requests per minute


@dataclass(frozen=True)
class EmailConfig:
    """Gmail IMAP/SMTP settings."""
    user: str = ""
    password: str = ""
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    poll_interval: int = 20


@dataclass(frozen=True)
class SecurityConfig:
    """Security and validation settings."""
    max_command_length: int = 10000
    max_payload_size: int = 1_000_000
    api_key: str = ""
    hmac_secret: str = ""


@dataclass(frozen=True)
class LoggingConfig:
    """Logging output settings."""
    level: str = "INFO"
    log_dir: str = str(Path.cwd() / "agent_logs")
    console_output: bool = True
    file_output: bool = True
    sanitize_secrets: bool = True
    max_log_size_mb: int = 50


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline execution settings."""
    max_concurrent_steps: int = 4
    step_timeout: int = 120
    checkpoint_dir: str = str(Path.cwd() / "agent_data" / "checkpoints")
    screenshot_on_error: bool = True
    video_dir: str = str(Path.cwd())


@dataclass(frozen=True)
class EngineConfig:
    """Master configuration - all settings from environment variables."""
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "EngineConfig":
        """Load configuration from .env file and environment variables."""
        env_path = Path(env_file) if env_file else Path.cwd() / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        return cls(
            browser=BrowserConfig(
                headless=os.getenv("BROWSER_HEADLESS", "0").lower() in ("1", "true", "yes"),
                user_data_dir=os.getenv("BROWSER_USER_DATA_DIR", str(Path.home() / ".ghost_browser_profile")),
                viewport_width=int(os.getenv("BROWSER_VIEWPORT_WIDTH", "1280")),
                viewport_height=int(os.getenv("BROWSER_VIEWPORT_HEIGHT", "720")),
                locale=os.getenv("BROWSER_LOCALE", "en-US"),
                timezone_id=os.getenv("BROWSER_TIMEZONE", "America/Los_Angeles"),
                block_resources=os.getenv("BROWSER_BLOCK_RESOURCES", "1").lower() in ("1", "true"),
                max_pages=int(os.getenv("BROWSER_MAX_PAGES", "5")),
                navigation_timeout_ms=int(os.getenv("BROWSER_NAV_TIMEOUT", "30000")),
                action_timeout_ms=int(os.getenv("BROWSER_ACTION_TIMEOUT", "15000")),
            ),
            llm=LLMConfig(
                gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
                gemini_model=os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
                hermes_url=os.getenv("HERMES_URL", "http://localhost:11434"),
                hermes_model=os.getenv("HERMES_MODEL", "llama3.2:1b"),
                hermes_timeout=int(os.getenv("HERMES_TIMEOUT", "15")),
                gemini_timeout=int(os.getenv("GEMINI_TIMEOUT", "30")),
                max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
                rate_limit_rpm=int(os.getenv("LLM_RATE_LIMIT_RPM", "15")),
            ),
            email=EmailConfig(
                user=os.getenv("GMAIL_USER", ""),
                password=os.getenv("GMAIL_PASS", ""),
                imap_host=os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com"),
                imap_port=int(os.getenv("GMAIL_IMAP_PORT", "993")),
                smtp_host=os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com"),
                smtp_port=int(os.getenv("GMAIL_SMTP_PORT", "465")),
                poll_interval=int(os.getenv("EMAIL_POLL_INTERVAL", "20")),
            ),
            security=SecurityConfig(
                max_command_length=int(os.getenv("SEC_MAX_COMMAND_LENGTH", "10000")),
                max_payload_size=int(os.getenv("SEC_MAX_PAYLOAD_SIZE", "1000000")),
                api_key=os.getenv("GHOST_API_KEY", ""),
                hmac_secret=os.getenv("GHOST_HMAC_SECRET", ""),
            ),
            logging=LoggingConfig(
                level=os.getenv("LOG_LEVEL", "INFO").upper(),
                log_dir=os.getenv("LOG_DIR", str(Path.cwd() / "agent_logs")),
                console_output=os.getenv("LOG_CONSOLE", "1").lower() in ("1", "true"),
                file_output=os.getenv("LOG_FILE_OUTPUT", "1").lower() in ("1", "true"),
                sanitize_secrets=os.getenv("LOG_SANITIZE", "1").lower() in ("1", "true"),
                max_log_size_mb=int(os.getenv("LOG_MAX_SIZE_MB", "50")),
            ),
            pipeline=PipelineConfig(
                max_concurrent_steps=int(os.getenv("PIPELINE_MAX_CONCURRENT", "4")),
                step_timeout=int(os.getenv("PIPELINE_STEP_TIMEOUT", "120")),
                checkpoint_dir=os.getenv("PIPELINE_CHECKPOINT_DIR", str(Path.cwd() / "agent_data" / "checkpoints")),
                screenshot_on_error=os.getenv("PIPELINE_SCREENSHOT_ON_ERROR", "1").lower() in ("1", "true"),
                video_dir=os.getenv("PIPELINE_VIDEO_DIR", str(Path.cwd())),
            ),
        )

    def validate(self) -> list[str]:
        """Return list of configuration warnings (empty = all good)."""
        warnings = []
        if not self.llm.gemini_api_key:
            warnings.append("GEMINI_API_KEY not set - Gemini fallback unavailable")
        if not self.email.user:
            warnings.append("GMAIL_USER not set - email features unavailable")
        if not self.security.api_key:
            warnings.append("GHOST_API_KEY not set - API authentication disabled")
        path = Path(self.browser.user_data_dir)
        if not path.exists():
            warnings.append(f"Browser profile dir does not exist: {path}")
        return warnings
