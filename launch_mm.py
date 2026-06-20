import json, os, time, shutil, socket, subprocess
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.getenv("BROWSER_USER_DATA_DIR", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data")) + "\\" + os.getenv("GMAIL_PROFILE", "Profile_Auto")
CHROME_EXE = os.getenv("CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
EXT_ID = "nkbihfbeogaeaoehlefnkodbefgpgknn"
EXT_VER = "13.35.1.0"
EXT_SRC = os.path.join(PROFILE_DIR, "Extensions", EXT_ID, EXT_VER + "_0")
EXT_DST = os.path.join(PROFILE_DIR, "Extensions", EXT_ID, EXT_VER)

os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(3)

# Ensure correct directory name (Chrome Web Store format: version_0)
if not os.path.exists(EXT_SRC):
    print(f"Extension source missing: {EXT_SRC}", flush=True)
    exit()

print(f"Extension path: {EXT_SRC}", flush=True)

# Add to Preferences
prefs_path = os.path.join(PROFILE_DIR, "Preferences")
if os.path.exists(prefs_path):
    with open(prefs_path, "r", encoding="utf-8") as f:
        prefs = json.load(f)

    # Read the key from manifest
    manifest_path = os.path.join(EXT_SRC, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    ext_entry = {
        "active_permissions": {
            "api": ["activeTab", "storage", "alarms"],
            "explicit_host": [],
            "manifest_permissions": [],
            "scriptable_host": []
        },
        "commands": {},
        "content_settings": [],
        "creation_flags": 1,
        "from_webstore": True,
        "granted_permissions": {
            "api": ["activeTab", "storage", "alarms"],
            "explicit_host": [],
            "manifest_permissions": [],
            "scriptable_host": []
        },
        "incognito_content_settings": [],
        "install_time": "13000000000000000",
        "location": 1,
        "manifest": {
            "name": manifest.get("name"),
            "version": manifest.get("version"),
            "manifest_version": manifest.get("manifest_version"),
        },
        "may_disable": True,
        "path": EXT_SRC.replace("\\", "/"),
        "preferences": {},
        "state": 1,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
    }

    prefs.setdefault("extensions", {}).setdefault("settings", {})[EXT_ID] = ext_entry
    
    with open(prefs_path, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
    print("Extension registered in Preferences", flush=True)

# Create Extension State file
ext_state_dir = os.path.join(PROFILE_DIR, "Extension State")
os.makedirs(ext_state_dir, exist_ok=True)
with open(os.path.join(ext_state_dir, EXT_ID + ".json"), "w") as f:
    json.dump({"install_time": "13000000000000000", "version": EXT_VER}, f)
print("Extension state file created", flush=True)

# Launch Chrome
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
        print(f"CDP ready after {i+1}s", flush=True)
        break
    s.close()

time.sleep(5)

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    
    # Navigate directly to MetaMask
    mm_url = f"chrome-extension://{EXT_ID}/home.html"
    print(f"Opening: {mm_url}", flush=True)
    
    try:
        page.goto(mm_url, timeout=20000, wait_until="domcontentloaded")
        time.sleep(3)
        print(f"SUCCESS! Title: {page.title()}", flush=True)
        print(f"URL: {page.url[:120]}", flush=True)
        body = page.inner_text("body")[:3000]
        print(f"Body:\n{body}", flush=True)
        page.screenshot(path="D:\\DDecentralized_AI_Agent\\metamask.png")
        print("Screenshot saved!", flush=True)
        
        # Look for password/ unlock form
        if "unlock" in body.lower() or "password" in body.lower():
            print("\nUNLOCK PAGE DETECTED!", flush=True)
            # Fill password
            pw_input = page.query_selector("input[type='password']")
            if pw_input:
                pw_input.fill(os.getenv("METAMASK_PASSWORD", ""))
                print("Password filled", flush=True)
                # Click unlock
                unlock_btn = page.query_selector("button:has-text('Unlock')")
                if unlock_btn:
                    unlock_btn.click()
                    print("Clicked Unlock", flush=True)
                    time.sleep(5)
                    print(f"After unlock: {page.inner_text('body')[:500]}", flush=True)
        
    except Exception as e:
        print(f"Failed: {e}", flush=True)
    
    time.sleep(10)

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
