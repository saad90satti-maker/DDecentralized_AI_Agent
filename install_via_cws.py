import subprocess, time, socket, requests, json, os

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"

os.system("taskkill /f /im chrome.exe >nul 2>&1")
time.sleep(3)

# Launch with debugging port
proc = subprocess.Popen([
    CHROME,
    f"--user-data-dir={PROFILE_DIR}",
    "--remote-debugging-port=9222",
    "--no-first-run",
    "--no-default-browser-check",
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for i in range(20):
    time.sleep(1)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    if s.connect_ex(("127.0.0.1", 9222)) == 0:
        s.close()
        break
    s.close()

time.sleep(3)

# Get WebSocket URL
resp = requests.get("http://127.0.0.1:9222/json", timeout=5)
tabs = resp.json()

# Find the MetaMask CWS page or create a new tab
ws_url = None
for tab in tabs:
    if "metamask" in tab.get("url", "") or "chromewebstore" in tab.get("url", ""):
        ws_url = tab.get("webSocketDebuggerUrl")
        break

if not ws_url:
    # Navigate to CWS in an existing tab
    if tabs:
        ws_url = tabs[1].get("webSocketDebuggerUrl") if len(tabs) > 1 else tabs[0].get("webSocketDebuggerUrl")

if ws_url:
    from websocket import create_connection
    ws = create_connection(ws_url, timeout=10)
    
    # Navigate to MetaMask page
    nav = {"id": 1, "method": "Page.navigate", "params": {"url": "https://chromewebstore.google.com/detail/metamask/nkbihfbeogaeaoehlefnkodbefgpgknn"}}
    ws.send(json.dumps(nav))
    time.sleep(5)
    
    recv = ws.recv()
    print(f"Nav response: {json.dumps(json.loads(recv))[:200]}", flush=True)
    
    # Enable Runtime domain
    ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
    time.sleep(0.5)
    ws.recv()
    
    # Click "Add to Chrome" button via JavaScript
    script = """
    (() => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.includes('Add to Chrome')) {
                btn.click();
                return 'Clicked Add to Chrome';
            }
        }
        // Try div based buttons
        const divs = document.querySelectorAll('div[role="button"]');
        for (const div of divs) {
            if (div.textContent.includes('Add to Chrome')) {
                div.click();
                return 'Clicked Add to Chrome (div)';
            }
        }
        return 'Button not found';
    })()
    """
    result = {"id": 3, "method": "Runtime.evaluate", "params": {"expression": script, "returnByValue": True}}
    ws.send(json.dumps(result))
    time.sleep(3)
    
    resp3 = json.loads(ws.recv())
    click_result = resp3.get("result", {}).get("result", {}).get("value", "unknown")
    print(f"Click result: {click_result}", flush=True)
    
    time.sleep(3)
    
    # Try to click the "Add extension" dialog button
    script2 = """
    (() => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.includes('Add extension')) {
                btn.click();
                return 'Add extension clicked';
            }
        }
        // Check for dialog
        const dialogs = document.querySelectorAll('cr-dialog, cr-action-menu, [role="dialog"]');
        return `Dialogs found: ${dialogs.length}`;
    })()
    """
    result2 = {"id": 4, "method": "Runtime.evaluate", "params": {"expression": script2, "returnByValue": True}}
    ws.send(json.dumps(result2))
    time.sleep(3)
    resp4 = json.loads(ws.recv())
    print(f"Dialog result: {resp4.get('result',{}).get('result',{}).get('value','?')}", flush=True)
    
    ws.close()

time.sleep(5)
proc.terminate()
os.system("taskkill /f /im chrome.exe >nul 2>&1")
