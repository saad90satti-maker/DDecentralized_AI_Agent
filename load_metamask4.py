import json, os, shutil, time, socket, subprocess
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# Kill Chrome
os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(4)

# Add extension to Chrome Preferences so it's recognized as installed
prefs_path = os.path.join(PROFILE_DIR, "Preferences")
if os.path.exists(prefs_path):
    with open(prefs_path, "r", encoding="utf-8") as f:
        prefs = json.load(f)
    
    ext_id = "nkbihfbeogaeaoehlefnkodbefgpgknn"
    ext_version = "13.35.1.0"
    ext_path = os.path.join(PROFILE_DIR, "Extensions", ext_id, ext_version + "_0").replace("\\", "/")
    
    ext_settings = {
        "active_permissions": {"api": [], "explicit_host": [], "manifest_permissions": [], "scriptable_host": []},
        "commands": {},
        "content_settings": [],
        "creation_flags": 1,
        "dependencies": [],
        "has_container_web_app": False,
        "from_bookmark": False,
        "from_webstore": True,
        "granted_permissions": {"api": [], "explicit_host": [], "manifest_permissions": [], "scriptable_host": []},
        "incognito_content_settings": [],
        "incognito_preferences": {},
        "install_time": "13000000000000000",
        "location": 1,
        "manifest": {
            "name": "__MSG_appName__",
            "version": ext_version,
        },
        "may_disable": True,
        "path": ext_path,
        "preferences": {},
        "regular_only_preferences": {},
        "state": 1,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
    }
    
    if "extensions" not in prefs:
        prefs["extensions"] = {}
    if "settings" not in prefs["extensions"]:
        prefs["extensions"]["settings"] = {}
    
    if ext_id not in prefs["extensions"]["settings"]:
        prefs["extensions"]["settings"][ext_id] = ext_settings
        print(f"Extension {ext_id} added to Preferences", flush=True)
    else:
        print(f"Extension already in Preferences", flush=True)
    
    with open(prefs_path, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
    
    # Also need to create state files in the Extension State folder
    ext_state_dir = os.path.join(PROFILE_DIR, "Extension State")
    os.makedirs(ext_state_dir, exist_ok=True)
    
    # Write a simple state file
    state_path = os.path.join(ext_state_dir, ext_id + ".json")
    with open(state_path, "w") as f:
        json.dump({"install_time": "13000000000000000", "version": ext_version}, f)
    print("Extension state file created", flush=True)

# Now launch Chrome
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
    
    mm_url = f"chrome-extension://{ext_id}/home.html"
    print(f"Opening: {mm_url}", flush=True)
    
    for attempt in range(3):
        try:
            page.goto(mm_url, timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            print(f"Title: {page.title()}", flush=True)
            print(f"URL: {page.url[:120]}", flush=True)
            body = page.inner_text("body")[:2000]
            print(f"Body:\n{body}", flush=True)
            page.screenshot(path="D:\\DDecentralized_AI_Agent\\metamask.png")
            break
        except Exception as e:
            print(f"Attempt {attempt+1}: {e}", flush=True)
            time.sleep(3)
    
    time.sleep(10)

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
