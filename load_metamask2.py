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
    "--enable-automation",
    "--enable-logging=stderr",
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
    
    # Get CDP session to investigate extension IDs
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    
    # Method 1: Get all targets and look for extension pages
    targets = cdp.send("Target.getTargets").get("targetInfos", [])
    print(f"Targets ({len(targets)}):", flush=True)
    for t in targets:
        url = t.get("url", "")
        if "extension" in url.lower() or "chrome-extension" in url:
            print(f"  EXTENSION: {t['type']}: {url}", flush=True)
        else:
            print(f"  {t['type']}: {url[:100]}", flush=True)
    
    # Method 2: Try to use chrome.management API
    try:
        page.goto("about:blank", timeout=5000)
        # Inject and run the management API
        result = page.evaluate("""
            async () => {
                try {
                    const ext = await new Promise((resolve, reject) => {
                        chrome.management.getAll(exts => resolve(exts));
                    });
                    return JSON.stringify(ext.map(e => ({id: e.id, name: e.name, enabled: e.enabled})));
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }
        """)
        print(f"\nManagement API: {result}", flush=True)
    except Exception as e:
        print(f"\nManagement API error: {e}", flush=True)
    
    # Method 3: Check the Preferences for extensions settings
    prefs_path = os.path.join(PROFILE_DIR, "Preferences")
    if os.path.exists(prefs_path):
        with open(prefs_path, encoding="utf-8") as f:
            prefs = json.load(f)
        ext_settings = prefs.get("extensions", {}).get("settings", {})
        loaded_ids = list(ext_settings.keys())
        print(f"\nExtensions in Preferences: {loaded_ids or 'NONE'}", flush=True)
    
    time.sleep(10)

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
