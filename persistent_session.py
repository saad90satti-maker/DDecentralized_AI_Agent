import json, os, time, logging, sys
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    encoding="utf-8",
)
logger = logging.getLogger("SessionManager")

BASE_DIR = Path(__file__).resolve().parent
COOKIE_DIR = BASE_DIR / "session_data"
COOKIE_DIR.mkdir(exist_ok=True)

PROFILE_DIR = os.getenv("BROWSER_USER_DATA_DIR", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data"))
PROFILE_NAME = os.getenv("GMAIL_PROFILE", "Profile_Auto")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")


@dataclass
class ServiceTab:
    name: str
    url: str
    page: Optional[Page] = None
    cookie_file: str = ""
    logged_in_check: str = ""
    login_required: bool = True

    def __post_init__(self):
        if not self.cookie_file:
            safe = self.name.lower().replace(" ", "_")
            self.cookie_file = str(COOKIE_DIR / f"{safe}_cookies.json")


SERVICES = [
    ServiceTab(
        name="Gmail",
        url="https://mail.google.com/mail/u/0/#inbox",
        logged_in_check="mail.google.com/mail",
    ),
    ServiceTab(
        name="YouTube",
        url="https://www.youtube.com",
        logged_in_check="youtube.com",
    ),
    ServiceTab(
        name="Google Maps",
        url="https://maps.google.com",
        logged_in_check="maps.google.com",
        login_required=False,
    ),
    ServiceTab(
        name="Google Drive",
        url="https://drive.google.com/drive/my-drive",
        logged_in_check="drive.google.com/drive",
    ),
    ServiceTab(
        name="Cloud Console",
        url="https://console.cloud.google.com",
        logged_in_check="console.cloud.google.com",
    ),
]


class PersistentSessionManager:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.services: Dict[str, ServiceTab] = {}
        self._running = False

    def start(self):
        logger.info("Starting persistent browser session...")
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=self.headless,
            args=[
                f"--profile-directory={PROFILE_NAME}",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            no_viewport=True,
        )
        logger.info(f"Context ready | Profile: {PROFILE_NAME}")

    def restore_cookies(self, service: ServiceTab) -> bool:
        path = Path(service.cookie_file)
        if not path.exists():
            return False
        try:
            cookies = json.loads(path.read_text())
            self.context.add_cookies(cookies)
            logger.info(f"  Cookies restored: {service.name} ({len(cookies)} cookies)")
            return True
        except Exception as e:
            logger.warning(f"  Cookie restore failed for {service.name}: {e}")
            return False

    def save_cookies(self, service: ServiceTab):
        if not service.page:
            return
        try:
            cookies = self.context.cookies()
            Path(service.cookie_file).write_text(json.dumps(cookies, indent=2))
            logger.info(f"  Cookies saved: {service.name} ({len(cookies)} cookies)")
        except Exception as e:
            logger.warning(f"  Cookie save failed for {service.name}: {e}")

    def save_all_cookies(self):
        for svc in self.services.values():
            self.save_cookies(svc)

    def _google_login(self, page: Page):
        logger.info("  Performing Google login...")
        page.goto("https://accounts.google.com/signin", timeout=30000, wait_until="networkidle")
        time.sleep(3)

        try:
            # Handle account chooser: click the saved account
            account = page.query_selector("[data-identifier='saad90satti@gmail.com']")
            if account:
                logger.info("  Account chooser: clicking saved account")
                account.click()
                time.sleep(3)
            else:
                # Standard sign-in: fill email
                page.wait_for_selector("#identifierId", timeout=10000)
                email_val = page.get_attribute("#identifierId", "value")
                if email_val:
                    page.click("#identifierNext")
                else:
                    page.fill("#identifierId", GMAIL_USER)
                    page.click("#identifierNext")
                time.sleep(3)

            # Fill password
            page.wait_for_selector("input[type='password']", timeout=10000)
            time.sleep(1)
            page.fill("input[type='password']", GMAIL_PASS)
            page.click("#passwordNext")
            time.sleep(5)
            logger.info("  Login completed")
            return True
        except Exception as e:
            logger.error(f"  Login failed: {e}")
            return False

    def is_authenticated(self, page: Page, service: ServiceTab) -> bool:
        url = page.url
        if "accounts.google.com" in url or "signin" in url.lower():
            return False
        if service.logged_in_check and service.logged_in_check in url:
            return True
        if "google.com" not in url:
            return False
        return True

    def _navigate_retry(self, page: Page, url: str, max_retries: int = 2):
        for attempt in range(max_retries):
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)
                if url.split("/")[2] in page.url or page.url.startswith(url.split("/")[0]):
                    return True
                logger.info(f"  Redirected to {page.url.split('?')[0]}, retrying...")
            except Exception as e:
                logger.warning(f"  Nav attempt {attempt+1} failed: {e}")
                time.sleep(2)
        return False

    def open_service(self, service: ServiceTab) -> Page:
        logger.info(f"Opening {service.name} -> {service.url}")
        page = self.context.new_page()

        self.restore_cookies(service)

        ok = self._navigate_retry(page, service.url)

        if service.login_required and not self.is_authenticated(page, service):
            logger.info(f"  {service.name}: not authenticated, attempting login")
            self._google_login(page)
            ok = self._navigate_retry(page, service.url)

        if self.is_authenticated(page, service):
            logger.info(f"  {service.name}: authenticated [OK]")
        else:
            logger.warning(f"  {service.name}: auth uncertain, retrying...")
            self._google_login(page)
            ok = self._navigate_retry(page, service.url)
            if self.is_authenticated(page, service):
                logger.info(f"  {service.name}: authenticated [OK] after retry")

        self.save_cookies(service)
        service.page = page
        self.services[service.name] = service
        return page

    def open_all_services(self):
        for svc in SERVICES:
            try:
                self.open_service(svc)
            except Exception as e:
                logger.error(f"Failed to open {svc.name}: {e}")

    def refresh_all(self):
        logger.info("Refreshing all service tabs...")
        for svc in self.services.values():
            if svc.page and not svc.page.is_closed():
                try:
                    svc.page.reload(wait_until="networkidle")
                    time.sleep(1)
                except:
                    pass

    def close(self):
        self.save_all_cookies()
        logger.info("Closing session...")
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()
        logger.info("Session closed")

    def run_forever(self, poll_interval: int = 300):
        self.start()
        self.open_all_services()
        logger.info(f"Session running. Polling every {poll_interval}s. Press Ctrl+C to stop.")
        self._running = True

        try:
            while self._running:
                time.sleep(poll_interval)
                for svc in self.services.values():
                    if svc.page and not svc.page.is_closed():
                        try:
                            current = svc.page.url
                            if "accounts.google.com" in current:
                                logger.info(f"  {svc.name}: session expired")
                                self._google_login(svc.page)
                                svc.page.goto(svc.url, timeout=30000, wait_until="networkidle")
                                self.save_cookies(svc)
                        except:
                            pass
                self.save_all_cookies()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            self.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Persistent Browser Session Manager")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--poll", type=int, default=300, help="Session check interval (seconds)")
    args = parser.parse_args()

    manager = PersistentSessionManager(headless=args.headless)
    manager.run_forever(poll_interval=args.poll)
