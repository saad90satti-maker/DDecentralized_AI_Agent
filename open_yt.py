from playwright.sync_api import sync_playwright
import time

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"
PROFILE = "Profile_Auto"

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=False,
        args=["--profile-directory=" + PROFILE, "--disable-blink-features=AutomationControlled"],
    )
    page = browser.new_page()
    page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)
    print(f"YouTube: {page.title()}", flush=True)
    time.sleep(5)
    browser.close()
