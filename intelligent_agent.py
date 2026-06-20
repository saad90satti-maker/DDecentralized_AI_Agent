"""
Intelligent Browser Agent
=========================
Vision-driven automation that reads page state, makes decisions,
and self-corrects instead of following rigid paths.

Usage:
    pip install selenium webdriver-manager
    python intelligent_agent.py
"""

import os
import re
import sys
from datetime import datetime
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    NoSuchElementException,
)
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

SEARCH_QUERY = "Top AI trends 2026"
PERSISTENT_PROFILE = None  # Set to a path to reuse existing logged-in sessions (close Chrome first)
LOG_FILE = "agent_actions.log"


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# DRIVER SETUP
# ---------------------------------------------------------------------------

def build_driver() -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()

    # Stability
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-software-rasterizer")

    # Stealth
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--disable-blink-features=AutomationControlled")

    # Session persistence
    if PERSISTENT_PROFILE and os.path.isdir(PERSISTENT_PROFILE):
        log(f"Using persistent profile: {PERSISTENT_PROFILE}")
        opts.add_argument(f"--user-data-dir={PERSISTENT_PROFILE}")
        opts.add_argument("--profile-directory=Default")
    else:
        # Use a temp profile to avoid conflicts with running Chrome
        temp_profile = os.path.join(os.environ.get("TEMP", "."), "selenium_profile")
        opts.add_argument(f"--user-data-dir={temp_profile}")

    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver


# ---------------------------------------------------------------------------
# HELPER: safe waiter
# ---------------------------------------------------------------------------

def wait_or_none(driver, by, selector, timeout=8):
    """Return element if it appears within timeout, else None."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, selector))
        )
    except (TimeoutException, WebDriverException):
        return None


def find_or_none(parent, by, selector):
    """Return first matching child element or None."""
    try:
        return parent.find_element(by, selector)
    except (NoSuchElementException, WebDriverException):
        return None


# ---------------------------------------------------------------------------
# STEP 1 — handle cookie / consent modals
# ---------------------------------------------------------------------------

def dismiss_consent(driver, wait: WebDriverWait) -> None:
    lookups = [
        (By.XPATH, "//button[contains(., 'Accept all')]"),
        (By.XPATH, "//button[contains(., 'Reject all')]"),
        (By.XPATH, "//button[contains(., 'I agree')]"),
        (By.XPATH, "//button[contains(., 'Customize')]"),
        (By.XPATH, "//div[@role='dialog']//button"),
        (By.CSS_SELECTOR, "[aria-label*='cookie'] button, [aria-label*='consent'] button"),
    ]
    for by, sel in lookups:
        btn = wait_or_none(driver, by, sel, timeout=3)
        if btn:
            log(f"Dismissing consent dialog via ({by}, {sel})")
            try:
                btn.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click()", btn)
            return


# ---------------------------------------------------------------------------
# STEP 2 — Google search
# ---------------------------------------------------------------------------

def google_search(driver, query: str) -> None:
    log(f"Navigating to Google …")
    driver.get("https://www.google.com")

    dismiss_consent(driver, WebDriverWait(driver, 5))

    # Locate search box and type query
    search_box = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.NAME, "q"))
    )
    search_box.clear()
    search_box.send_keys(query)
    search_box.send_keys(Keys.RETURN)
    log(f"Searched for '{query}' …")


# ---------------------------------------------------------------------------
# STEP 3 — Parse results, filter ads, return organic list
# ---------------------------------------------------------------------------

def parse_organic_results(driver) -> list[dict]:
    """
    Return up to `limit` organic (non-ad) search results.
    Each dict: {title, url, snippet, element}
    """
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#search")))

    results_container = driver.find_element(By.CSS_SELECTOR, "#search")
    all_links = results_container.find_elements(By.XPATH, ".//a[.//h3]")

    organic: list[dict] = []
    for a in all_links:
        if len(organic) >= 3:
            break

        try:
            title_elem = a.find_element(By.XPATH, ".//h3")
            title = title_elem.text.strip()
        except NoSuchElementException:
            continue

        href = a.get_attribute("href") or ""
        if not href or href.startswith("http://www.google.com/search") or "/search?" in href:
            continue

        # AD DETECTION: walk up the DOM to find a parent that
        # contains "Ad" or "Sponsored" indicator.
        parent = a
        is_ad = False
        for _ in range(6):
            parent = parent.find_element(By.XPATH, "..")
            try:
                text = parent.text
            except WebDriverException:
                text = ""
            if re.search(r'\bAd\b|Sponsored', text, re.IGNORECASE):
                is_ad = True
                break

        if is_ad:
            log(f"  [SKIP – AD] {title[:60]}")
            continue

        snippet_el = find_or_none(a, By.XPATH, "./ancestor::div[contains(@class,'g')]//div[@data-sncf]")
        snippet = snippet_el.text.strip() if snippet_el else ""

        organic.append({"title": title, "url": href, "snippet": snippet, "element": a})
        log(f"  [{len(organic)}] {title[:70]}")

    return organic


# ---------------------------------------------------------------------------
# STEP 4 — Choose best article candidate
# ---------------------------------------------------------------------------

def pick_best_article(results: list[dict]) -> Optional[dict]:
    """
    Pick the result most likely to be an article/blog.
    Heuristic:
    1. Prefer URLs containing common blogging / news platforms.
    2. Prefer longer titles (more substantive).
    3. Fall back to the first non-ad result.
    """
    if not results:
        return None

    # Score each result
    blog_signals = [
        "medium.com", "blog.", "/blog/", "substack.com",
        "forbes.com", "techcrunch.com", "wired.com", "theverge.com",
        "zdnet.com", "cnet.com", "arstechnica.com", "venturebeat.com",
        "thenextweb.com", "analyticsinsight.net", "towardsdatascience.com",
        "analyticsvidhya.com", "kdnuggets.com", "datasciencecentral.com",
        "newsletter.", "hashnode.dev", "dev.to", "hackernoon.com",
    ]

    scored = []
    for r in results:
        score = 0
        url_lower = r["url"].lower()
        for signal in blog_signals:
            if signal in url_lower:
                score += 10
        title_lower = r["title"].lower()
        if any(kw in title_lower for kw in ["trend", "2026", "ai", "artificial intelligence",
                                              "top", "future", "predict", "breakthrough"]):
            score += 5
        score += len(r["title"])  # longer titles often more substantive
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
    log(f"Picked article: {best['title'][:70]} (score {scored[0][0]})")
    return best


# ---------------------------------------------------------------------------
# STEP 5 — Extract main heading from article page
# ---------------------------------------------------------------------------

def extract_heading(driver, url: str) -> Optional[str]:
    log(f"Navigating to article …")
    original = driver.current_window_handle
    driver.execute_script("window.open()")
    driver.switch_to.window(driver.window_handles[-1])

    try:
        driver.get(url)
    except (TimeoutException, WebDriverException):
        log("Page load timed out — trying partial DOM …")

    wait = WebDriverWait(driver, 8)
    heading = None

    # Try common heading selectors
    heading_selectors = [
        (By.TAG_NAME, "h1"),
        (By.CSS_SELECTOR, "article h1"),
        (By.CSS_SELECTOR, "[class*='headline']"),
        (By.CSS_SELECTOR, "[class*='title'] h1"),
        (By.CSS_SELECTOR, "h2"),
        (By.CSS_SELECTOR, "article h2"),
        (By.CSS_SELECTOR, "meta[property='og:title']"),
    ]

    for by, sel in heading_selectors:
        try:
            if sel.startswith("meta"):
                el = driver.find_element(by, sel)
                content = el.get_attribute("content")
                if content:
                    heading = content.strip()
                    break
            el = wait_or_none(driver, by, sel, timeout=3)
            if el:
                text = el.text.strip()
                if text and len(text) > 10:
                    heading = text
                    break
        except (NoSuchElementException, WebDriverException):
            continue

    # Fallback: page title
    if not heading:
        try:
            heading = driver.title.strip()
        except WebDriverException:
            heading = None

    # Close the tab and switch back
    try:
        driver.close()
    except WebDriverException:
        pass
    try:
        driver.switch_to.window(original)
    except WebDriverException:
        pass

    return heading


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    driver: Optional[webdriver.Chrome] = None
    try:
        open(LOG_FILE, "w", encoding="utf-8").close()

        driver = build_driver()
        wait = WebDriverWait(driver, 10)

        # 1. Navigate and search
        google_search(driver, SEARCH_QUERY)

        # 2. Wait for results and parse
        log("\n— Parsing organic results —")
        results = parse_organic_results(driver)

        if not results:
            log("No organic results found. Dumping page source to debug.html …")
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            log("Aborting.")
            return

        log(f"\nFound {len(results)} organic result(s).")

        # 3. Pick best article
        best = pick_best_article(results)
        if not best:
            log("Could not pick an article. Aborting.")
            return

        # 4. Extract heading
        heading = extract_heading(driver, best["url"])

        # 5. Print result
        print("\n" + "=" * 65)
        print("  ✦  RESULT  ✦")
        print("=" * 65)
        print(f"  Article : {best['title']}")
        print(f"  URL     : {best['url']}")
        print(f"  Heading : {heading}")
        print("=" * 65)

        # Save report
        report = {
            "search_query": SEARCH_QUERY,
            "selected_title": best["title"],
            "selected_url": best["url"],
            "extracted_heading": heading,
        }
        with open("agent_report.json", "w", encoding="utf-8") as f:
            import json
            json.dump(report, f, indent=2)
        log("Report saved to agent_report.json")

    except Exception as exc:
        log(f"FATAL: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if driver:
            log("Closing browser …")
            driver.quit()

    log("Done.")


if __name__ == "__main__":
    main()
