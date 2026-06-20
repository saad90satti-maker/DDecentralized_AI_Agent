import subprocess, time, socket, os

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE_DIR = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data"

# Kill all Chrome by name
subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], capture_output=True)
time.sleep(5)

cmd = [
    CHROME_EXE,
    f"--user-data-dir={PROFILE_DIR}",
    "--profile-directory=Profile_Auto",
    "--remote-debugging-port=9227",
    "--no-first-run",
    "--no-default-browser-check",
]
print("Launching Chrome with Profile_Auto...", flush=True)
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for i in range(20):
    time.sleep(1)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    if s.connect_ex(("127.0.0.1", 9227)) == 0:
        s.close()
        print(f"CDP ready after {i+1}s", flush=True)
        proc.terminate()
        time.sleep(2)
        subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], capture_output=True)
        exit(0)
    s.close()

print("CDP NOT ready", flush=True)
proc.terminate()
subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], capture_output=True)
