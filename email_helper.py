import json, os, time
from playwright.sync_api import sync_playwright

COOKIE_FILE = os.path.join(os.path.dirname(__file__), "gmail_cookies.json")
PROFILE_DIR = os.getenv("BROWSER_USER_DATA_DIR", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data"))
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")
PROFILE = os.getenv("GMAIL_PROFILE", "Profile_Auto")

def get_gmail_page(p, headless=False):
    browser = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=headless,
        args=["--profile-directory=" + PROFILE, "--disable-blink-features=AutomationControlled"],
    )
    page = browser.new_page()
    page.goto("https://mail.google.com/mail/u/0/#inbox", timeout=30000, wait_until="domcontentloaded")
    time.sleep(2)

    # If redirected to login, restore cookies or re-login
    if "accounts.google.com" in page.url:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
            page.context.add_cookies(cookies)
            page.goto("https://mail.google.com/mail/u/0/#inbox", timeout=30000)
            time.sleep(3)
        if "accounts.google.com" in page.url:
            _do_login(page)
    return browser, page

def _do_login(page):
    page.goto("https://accounts.google.com/signin", timeout=30000)
    time.sleep(2)
    page.fill("#identifierId", GMAIL_USER)
    page.click("#identifierNext")
    time.sleep(3)
    page.fill("input[type='password']", GMAIL_PASS)
    page.click("#passwordNext")
    time.sleep(5)
    # Save cookies after login
    cookies = page.context.cookies()
    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f, indent=2)
    print("Re-logged in and cookies saved", flush=True)

def get_yt_page(p, headless=False):
    browser = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_DIR,
        headless=headless,
        args=["--profile-directory=" + PROFILE, "--disable-blink-features=AutomationControlled"],
    )
    page = browser.new_page()
    page.goto("https://www.youtube.com", timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)
    return browser, page

def get_inbox_emails(page, limit=10):
    emails = []
    try:
        rows = page.query_selector_all("tr.zA")
        for i, row in enumerate(rows[:limit]):
            sender_el = row.query_selector(".yW")
            subject_el = row.query_selector(".bog")
            snippet_el = row.query_selector(".y2")
            sender = sender_el.inner_text() if sender_el else ""
            subject = subject_el.inner_text() if subject_el else ""
            snippet = snippet_el.inner_text() if snippet_el else ""
            emails.append({"sender": sender, "subject": subject, "snippet": snippet})
    except:
        pass
    return emails

if __name__ == "__main__":
    with sync_playwright() as p:
        browser, page = get_gmail_page(p, headless=False)
        print(f"Title: {page.title()}", flush=True)
        time.sleep(5)
        browser.close()
