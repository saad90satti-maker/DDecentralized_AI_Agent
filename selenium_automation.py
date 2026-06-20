"""
Selenium Chrome Automation Bot
==============================
Professional-grade browser automation with session persistence,
stealth bypass, robust waits, and modular AI injection point.

Requirements:
    pip install selenium webdriver-manager
"""

import os
import json
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------------------
# CONFIGURATION — edit these values before running
# ---------------------------------------------------------------------------

TARGET_URL = "https://example.com"  # <-- CHANGE to your target URL

# Session persistence: uncomment and set your real Chrome profile path to
# reuse existing cookies / logged-in sessions.
# To find your profile path, open chrome://version/ in Chrome and copy the
# "Profile Path" value (everything up to and including "User Data").
#
# Example Windows path:
#   PERSISTENT_PROFILE = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"
#
# NOTE: Using a persistent profile requires Chrome to be fully closed first.

# PERSISTENT_PROFILE: Optional[str] = None
PERSISTENT_PROFILE: Optional[str] = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"

# ---------------------------------------------------------------------------
# STEP DEFINITIONS — inject your custom logic here
# ---------------------------------------------------------------------------

STEPS = [
    # {
    #     "description": "Click login button",
    #     "by": By.XPATH,
    #     "selector": "//button[contains(text(), 'Sign In')]",
    #     "action": "click",
    # },
    # {
    #     "description": "Type into search field",
    #     "by": By.CSS_SELECTOR,
    #     "selector": "input[name='q']",
    #     "action": "send_keys",
    #     "value": "hello world",
    #     "press_enter": True,
    # },
]

# ---------------------------------------------------------------------------
# CUSTOM LOGIC HOOK — override this function for AI-driven behaviour
# ---------------------------------------------------------------------------

def custom_logic(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """
    Placeholder for AI-driven or custom interactions.
    `driver`   – the active Chrome WebDriver instance.
    `wait`     – a WebDriverWait instance (default timeout 15 s).
    Example:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button")))
        btn.click()
    """
    # ── Your custom code starts here ──────────────────────────────────
    print("[custom_logic] No custom logic defined — edit the `custom_logic` function.")
    # ── Your custom code ends here ────────────────────────────────────


# ===================================================================
# BOILERPLATE — you should not need to change anything below this line
# ===================================================================

def create_chrome_options() -> webdriver.ChromeOptions:
    """Build ChromeOptions with stability, anti-bot, and (optional) profile flags."""
    opts = webdriver.ChromeOptions()

    # ---- Stability --------------------------------------------------
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    # ---- Stealth / anti-bot -----------------------------------------
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--disable-blink-features=AutomationControlled")

    # ---- Session persistence (reuse logged-in state) -----------------
    if PERSISTENT_PROFILE:
        opts.add_argument(f"--user-data-dir={PERSISTENT_PROFILE}")
        opts.add_argument("--profile-directory=Default")

    # ---- Misc -------------------------------------------------------
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")

    return opts


def execute_steps(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """Walk through the STEPS list and perform each action."""
    for i, step in enumerate(STEPS, 1):
        desc = step.get("description", f"Step {i}")
        print(f"  [{i}/{len(STEPS)}] {desc} ...")

        try:
            by = step["by"]
            sel = step["selector"]
            element = wait.until(EC.presence_of_element_located((by, sel)))

            action = step.get("action", "click")

            if action == "click":
                wait.until(EC.element_to_be_clickable((by, sel))).click()
            elif action == "send_keys":
                value = step.get("value", "")
                element.clear()
                element.send_keys(value)
                if step.get("press_enter"):
                    element.send_keys(Keys.RETURN)
            elif action == "wait_for_text":
                expected_text = step.get("value", "")
                wait.until(
                    EC.text_to_be_present_in_element((by, sel), expected_text)
                )

            print(f"    -> done")

        except (TimeoutException, WebDriverException) as exc:
            print(f"    -> FAILED: {exc}")
            raise


def main() -> None:
    """Orchestrate the entire automation run."""
    opts = create_chrome_options()

    driver: Optional[webdriver.Chrome] = None
    try:
        print("[main] Initialising Chrome driver ...")
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)

        wait = WebDriverWait(driver, timeout=15)

        print(f"[main] Navigating to {TARGET_URL} ...")
        driver.get(TARGET_URL)

        # Give the page a moment to settle (Selenium's get() waits for
        # the `load` event, but SPAs often need extra time).
        # A short implicit poll is safer than a hard sleep.
        driver.implicitly_wait(2)

        # ---- Run the step definitions --------------------------------
        if STEPS:
            print(f"[main] Executing {len(STEPS)} defined step(s) ...")
            execute_steps(driver, wait)
        else:
            print("[main] No STEPS defined — skipping automated walkthrough.")

        # ---- Run the custom-logic hook --------------------------------
        print("[main] Running custom_logic() ...")
        custom_logic(driver, wait)

        print("[main] Automation completed successfully.")

    except Exception as exc:
        print(f"[main] Fatal error: {exc}")
        raise
    finally:
        if driver:
            print("[main] Cleaning up — driver.quit() ...")
            driver.quit()


if __name__ == "__main__":
    main()
