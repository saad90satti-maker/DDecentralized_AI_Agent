import subprocess, time, socket, os

PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EXT_PATH = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Extensions\nkbihfbeogaeaoehlefnkodbefgpgknn\13.35.1.0_0"

os.system("taskkill /f /im chrome.exe 2>nul")
time.sleep(4)

# Launch Chrome WITHOUT CDP first, just test if the extension loads
cmd = f'"{CHROME_EXE}" --user-data-dir="{PROFILE_DIR}" --profile-directory=Profile_Auto --load-extension="{EXT_PATH}" --no-first-run --no-default-browser-check'
print(f"Running: {cmd[:150]}...", flush=True)

proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
time.sleep(8)

# Check if Chrome is running
import psutil
running = [p for p in psutil.process_iter(["pid", "name"]) if "chrome" in p.info["name"].lower()]
print(f"Chrome processes: {len(running)}", flush=True)

time.sleep(15)
print("Look at the Chrome window - is MetaMask loaded?", flush=True)
input("Press Enter to close...")

proc.terminate()
os.system("taskkill /f /im chrome.exe 2>nul")
