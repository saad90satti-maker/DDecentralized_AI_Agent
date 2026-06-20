import subprocess, time, socket, os

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CRX_PATH = os.path.join(PROFILE_DIR, "Extensions", "nkbihfbeogaeaoehlefnkodbefgpgknn", "13.35.1.0_0.crx")

os.system("taskkill /f /im chrome.exe >nul 2>&1")
time.sleep(3)

# Launch Chrome with CDP and NO automation flags
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

# Use requests to install extension via CDP
import requests, json

ws_url = None
try:
    r = requests.get("http://127.0.0.1:9222/json/version", timeout=5)
    data = r.json()
    ws_url = data.get("webSocketDebuggerUrl", "")
    print(f"WebSocket URL: {ws_url[:80]}...", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)

if ws_url:
    # Connect via websocket to install extension
    from websocket import create_connection
    ws = create_connection(ws_url, timeout=10)
    
    # Enable necessary domains
    ws.send(json.dumps({"id": 1, "method": "Management.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Target.setAutoAttach", "params": {"autoAttach": True, "waitForDebuggerOnStart": False}}))
    
    time.sleep(1)
    
    # Install the CRX
    ws.send(json.dumps({
        "id": 3,
        "method": "Management.installExtension",
        "params": {"id": "nkbihfbeogaeaoehlefnkodbefgpgknn"}
    }))
    
    time.sleep(5)
    
    # Read responses
    ws.settimeout(3)
    for _ in range(5):
        try:
            resp = json.loads(ws.recv())
            print(f"CDP response: {json.dumps(resp)[:200]}", flush=True)
        except:
            break
    
    # Install using extension ID directly
    ws.send(json.dumps({
        "id": 4,
        "method": "Page.navigate",
        "params": {"url": f"chrome-extension://nkbihfbeogaeaoehlefnkodbefgpgknn/home.html"}
    }))
    time.sleep(2)
    
    ws.close()

print("Done", flush=True)
proc.terminate()
