import subprocess, time, socket, os, json
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
EXT_PATH = os.path.join(PROFILE_DIR, "Extensions", "nkbihfbeogaeaoehlefnkodbefgpgknn", "13.35.1.0_0")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(4)

# Launch Chrome with Profile_Auto as user-data-dir and load the extension
cmd = [
    CHROME_EXE,
    f"--user-data-dir={PROFILE_DIR}",
    f"--load-extension={EXT_PATH}",
    "--remote-debugging-port=9222",
    "--no-first-run",
    "--no-default-browser-check",
]
print("Launching Chrome with MetaMask extension...", flush=True)
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
else:
    print("CDP not ready", flush=True)
    proc.terminate()
    exit(1)

time.sleep(3)

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    print("Connected!", flush=True)
    
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    
    mm_url = "chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn/home.html"
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
time.sleep(2)
os.system("taskkill /f /im chrome.exe 2>nul")
