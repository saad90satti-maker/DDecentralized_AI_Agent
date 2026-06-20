import subprocess, time, socket, os, json
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
EXT_PATH = os.path.join(PROFILE_DIR, "Extensions", "nkbihfbeogaeaoehlefnkodbefgpgknn", "13.35.1.0_0")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(4)

cmd = [
    CHROME_EXE,
    f"--user-data-dir={PROFILE_DIR}",
    f"--load-extension={EXT_PATH}",
    "--remote-debugging-port=9222",
    "--no-first-run",
    "--no-default-browser-check",
    "--silent-debugger-extension-api",
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
    cdp = context.new_cdp_session(context.new_page())
    
    # List ALL targets including service workers
    targets = cdp.send("Target.getTargets").get("targetInfos", [])
    print(f"All targets ({len(targets)}):", flush=True)
    for t in targets:
        type_ = t.get("type", "?")
        url = t.get("url", "")
        title = t.get("title", "")
        opener = t.get("openerId", "")
        opener_info = f" opener={opener[:12]}" if opener else ""
        print(f"  {type_}: {title[:40] if title else url[:100]}{opener_info}", flush=True)
    
    # Also try to get the extension's background service worker
    try:
        workers = cdp.send("ServiceWorker.deliverPushMessage")
    except:
        pass
    
    # Try connecting to any extension background page
    for t in targets:
        url = t.get("url", "")
        tid = t.get("targetId", "")
        if "chrome-extension" in url:
            print(f"\nFound extension target: {tid[:20]}... -> {url}", flush=True)
    
    time.sleep(10)

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
