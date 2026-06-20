import subprocess, time, os, socket, json
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EXT_ID = "nkbihfbeogaeaoehlefnkodbefgpgknn"
MM_PASS = "03255152854"

# Gracefully close Chrome (no taskkill)
os.system('taskkill /f /im chrome.exe >nul 2>&1')
time.sleep(3)

# Launch with CDP
cmd = [
    CHROME_EXE,
    f"--user-data-dir={PROFILE_DIR}",
    "--remote-debugging-port=9222",
    "--no-first-run",
    "--no-default-browser-check",
]
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for i in range(20):
    time.sleep(1)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    if s.connect_ex(("127.0.0.1", 9222)) == 0:
        s.close()
        break
    s.close()

time.sleep(5)

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    
    # Close any restore page dialog
    targets = cdp.send("Target.getTargets").get("targetInfos", [])
    for t in targets:
        if "restore" in t.get("url", "").lower() or "restore" in t.get("title", "").lower():
            print(f"Closing restore dialog: {t.get('url','')}", flush=True)
            cdp.send("Target.closeTarget", {"targetId": t.get("targetId")})
    
    # Try to access MetaMask
    mm_url = f"chrome-extension://{EXT_ID}/home.html"
    print(f"Opening MetaMask: {mm_url}", flush=True)
    
    try:
        page.goto(mm_url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(3)
        print(f"Title: {page.title()}", flush=True)
        print(f"URL: {page.url[:120]}", flush=True)
        body = page.inner_text("body")[:3000]
        print(f"Body:\n{body}", flush=True)
        
        # If unlock page - enter password
        if "unlock" in body.lower() or "password" in body.lower():
            print("\nUNLOCK PAGE - entering password...", flush=True)
            pw_input = page.query_selector("input[type='password']")
            if pw_input:
                pw_input.fill(MM_PASS)
                unlock_btn = page.query_selector("button:has-text('Unlock')") or page.query_selector("button:has-text('Import')")
                if unlock_btn:
                    unlock_btn.click()
                    print("Clicked Unlock", flush=True)
                    time.sleep(5)
                    body2 = page.inner_text("body")[:1000]
                    print(f"After unlock: {body2}", flush=True)
        
        page.screenshot(path="D:\\DDecentralized_AI_Agent\\metamask.png")
        
    except Exception as e:
        print(f"Failed: {e}", flush=True)
        # Check if extension is even loaded
        targets2 = cdp.send("Target.getTargets").get("targetInfos", [])
        for t in targets2:
            if EXT_ID in t.get("url", ""):
                print(f"Extension target found: {t}", flush=True)
    
    time.sleep(10)

proc.terminate()
time.sleep(3)
