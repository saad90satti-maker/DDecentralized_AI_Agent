from playwright.sync_api import sync_playwright
import time, os

PROFILE_DIR = os.getenv("BROWSER_USER_DATA_DIR", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data"))
EXT_PATH = os.getenv("METAMASK_EXT_PATH", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data\Profile_Auto\Extensions\nkbihfbeogaeaoehlefnkodbefgpgknn\13.35.1.0_0"))
EXT_ID = os.getenv("METAMASK_EXT_ID", "nkbihfbeogaeaoehlefnkodbefgpgknn")
MM_PASS = os.getenv("METAMASK_PASSWORD", "")

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=False,
        channel="chrome",
        args=[
            "--profile-directory=Profile_Auto",
            f"--load-extension={EXT_PATH}",
            "--disable-blink-features=AutomationControlled",
            "--silent-debugger-extension-api",
        ],
    )

    time.sleep(5)

    # Try to open MetaMask
    page = browser.new_page()
    mm_url = f"chrome-extension://{EXT_ID}/home.html"
    print(f"Opening: {mm_url}", flush=True)

    for attempt in range(3):
        try:
            page.goto(mm_url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            print(f"SUCCESS! Title: {page.title()}", flush=True)
            print(f"URL: {page.url[:120]}", flush=True)
            body = page.inner_text("body")[:3000]
            print(f"Body:\n{body}", flush=True)
            break
        except Exception as e:
            print(f"Attempt {attempt+1}: {e}", flush=True)
            time.sleep(3)

    time.sleep(10)
    browser.close()
