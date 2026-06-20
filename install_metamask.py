from playwright.sync_api import sync_playwright
import time, os

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=False,
        executable_path=CHROME_EXE,
        args=["--profile-directory=Profile_Auto", "--disable-blink-features=AutomationControlled"],
    )

    page = browser.new_page()
    page.goto("https://chromewebstore.google.com/detail/metamask/nkbihfbeogaeaoehlefnkodbefgpgknn", timeout=30000, wait_until="domcontentloaded")
    time.sleep(5)

    # Click "Add to Chrome" button
    btn = page.query_selector("button:has-text('Add to Chrome')")
    if btn:
        btn.click()
        print("Clicked Add to Chrome", flush=True)
    time.sleep(5)

    # Try to accept the dialog
    all_pages = browser.pages
    for pg in all_pages:
        try:
            add_ext = pg.wait_for_selector("button:has-text('Add extension')", timeout=3000)
            if add_ext:
                add_ext.click()
                print("Clicked Add extension", flush=True)
                break
        except:
            pass

    time.sleep(5)

    # Check if installed
    ext_path = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Extensions\nkbihfbeogaeaoehlefnkodbefgpgknn"
    if os.path.exists(ext_path):
        print(f"METAMASK INSTALLED!", flush=True)
    else:
        print("Not installed yet - you may need to click 'Add extension' manually", flush=True)
        print("The dialog should be visible on screen", flush=True)
        input("Press Enter after manually clicking 'Add extension'...")

        if os.path.exists(ext_path):
            print("METAMASK INSTALLED!", flush=True)
        else:
            print("Still not installed", flush=True)

    time.sleep(5)
    browser.close()
