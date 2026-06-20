"""
Human Mimicry Engine — Request delay randomization and browser fingerprinting.
Prevents pattern detection by randomizing all timing between automated actions.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("HumanMimicry")


@dataclass
class DelayProfile:
    """Configurable delay ranges for different action types."""
    between_requests: (float, float) = (5.0, 30.0)
    between_searches: (float, float) = (10.0, 45.0)
    between_clicks: (float, float) = (0.5, 3.0)
    between_keystrokes: (float, float) = (0.05, 0.25)
    page_load: (float, float) = (1.0, 5.0)
    form_fill: (float, float) = (2.0, 8.0)
    scroll: (float, float) = (0.5, 2.0)
    screenshot: (float, float) = (0.3, 1.0)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 Mobile/15E148 Safari/604.1",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.8,es;q=0.6",
    "en-GB,en;q=0.9,en-US;q=0.8",
    "en-CA,en;q=0.9,fr;q=0.8",
    "en-AU,en;q=0.9",
    "en-IN,en;q=0.8,hi;q=0.6",
]


class HumanMimicryEngine:
    def __init__(self, profile: Optional[DelayProfile] = None):
        self.profile = profile or DelayProfile()
        self._last_action_time: float = 0.0
        self._session_start: float = time.time()
        self._action_count: int = 0

    def random_delay(self, range_tuple: (float, float)) -> float:
        return round(random.uniform(*range_tuple), 2)

    def wait_between_requests(self) -> None:
        delay = self.random_delay(self.profile.between_requests)
        logger.debug("Delaying %.1fs (between requests)", delay)
        time.sleep(delay)

    def wait_between_searches(self) -> None:
        delay = self.random_delay(self.profile.between_searches)
        logger.debug("Delaying %.1fs (between searches)", delay)
        time.sleep(delay)

    def wait_page_load(self) -> None:
        delay = self.random_delay(self.profile.page_load)
        logger.debug("Delaying %.1fs (page load)", delay)
        time.sleep(delay)

    def wait_form_fill(self) -> None:
        delay = self.random_delay(self.profile.form_fill)
        logger.debug("Delaying %.1fs (form fill)", delay)
        time.sleep(delay)

    def wait_scroll(self) -> None:
        delay = self.random_delay(self.profile.scroll)
        logger.debug("Delaying %.1fs (scroll)", delay)
        time.sleep(delay)

    def wait_for_action(self, elapsed: float) -> None:
        """Ensure minimum time since last action (anti-bot)."""
        min_gap = 0.3
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)

    def random_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(ACCEPT_LANGUAGES),
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": random.choice(["1", "0"]),
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": random.choice(["max-age=0", "no-cache"]),
        }

    def record_action(self) -> None:
        now = time.time()
        if self._last_action_time > 0:
            self.wait_for_action(now - self._last_action_time)
        self._last_action_time = now
        self._action_count += 1

    @property
    def session_summary(self) -> Dict:
        return {
            "session_duration_s": round(time.time() - self._session_start, 1),
            "total_actions": self._action_count,
        }
