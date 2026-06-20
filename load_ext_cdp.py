import json, os, time, socket, subprocess
from playwright.sync_api import sync_playwright

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EXT_PATH = os.path.join(PROFILE_DIR, "Extensions", "nkbihfbeogaeaoehlefnkodbefgpgknn", "13.35.1.0_0")

os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(3)

cmd = [
    CHROME_EXE,
    f"--user-data-dir={PROFILE_DIR}",
    "--remote-debugging-port=9222",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-blink-features=AutomationControlled",
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
    
    # Navigate to extensions page
    page = context.new_page()
    
    # chrome://extensions doesn't work via goto, use CDP to navigate
    cdp = context.new_cdp_session(page)
    
    # Navigate to chrome://extensions using CDP
    cdp.send("Page.navigate", {"url": "chrome://extensions"})
    time.sleep(3)
    
    # Get page content via CDP
    result = cdp.send("Runtime.evaluate", {
        "expression": "document.body.innerText",
        "returnByValue": True
    })
    body = result.get("result", {}).get("value", "")
    print(f"Extensions page: {body[:2000]}", flush=True)
    
    # Enable Developer Mode
    cdp.send("Runtime.evaluate", {
        "expression": """
            document.querySelector('cr-toggle[id="devMode"]')?.click();
            // or try the toggle switch
            document.querySelector('.dev-toggle-container cr-toggle')?.click();
        """
    })
    time.sleep(2)
    
    # Click "Load unpacked" button
    cdp.send("Runtime.evaluate", {
        "expression": """
            // Find and click the Load unpacked button
            const buttons = document.querySelectorAll('cr-button');
            for (const btn of buttons) {
                if (btn.textContent.includes('Load unpacked')) {
                    btn.click();
                    break;
                }
            }
        """
    })
    time.sleep(2)
    
    result2 = cdp.send("Runtime.evaluate", {
        "expression": "document.body.innerText",
        "returnByValue": True
    })
    body2 = result2.get("result", {}).get("value", "")
    print(f"\nAfter load unpacked: {body2[:2000]}", flush=True)
    
    # Try a different approach - load unpacked via CDP
    # Use the file dialog to select the extension folder
    # Actually, we can use the extensions.loadUnpacked CDP method
    try:
        cdp.send("Page.dispatchEvent", {
            "type": "dragenter",
            "x": 0, "y": 0,
            "dataTransfer": {
                "items": [],
                "files": [],
                "types": []
            }
        })
    except:
        pass
    
    time.sleep(5)

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
