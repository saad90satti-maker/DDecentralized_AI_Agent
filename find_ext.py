import json, os, time, socket, subprocess
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EXT_ID = "nkbihfbeogaeaoehlefnkodbefgpgknn"

os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(3)

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

time.sleep(8)

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    
    # Get all targets
    targets = cdp.send("Target.getTargets").get("targetInfos", [])
    print(f"Targets ({len(targets)}):", flush=True)
    for t in targets:
        ttype = t.get("type", "?")
        url = t.get("url", "")
        tid = t.get("targetId", "")[:20]
        if "extension" in url or EXT_ID in url:
            print(f"  *** FOUND EXTENSION: {ttype} | {url} | {tid}", flush=True)
        else:
            print(f"  {ttype} | {url[:80]} | {tid}", flush=True)
    
    # Also try to discover via chrome.management (runs in page context)
    try:
        page.goto("about:blank", timeout=5000)
        # Try to inject the extension id into the page
        result = page.evaluate(f"""
            async () => {{
                // Try to access extension via chrome.runtime
                try {{
                    return await new Promise(r => chrome.runtime.sendMessage('{EXT_ID}', {{method: 'info'}}, r));
                }} catch(e) {{
                    return 'Error: ' + e.message;
                }}
            }}
        """)
        print(f"\nRuntime message: {result}", flush=True)
    except Exception as e:
        print(f"\nInject error: {e}", flush=True)
    
    time.sleep(5)

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
