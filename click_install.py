import pyautogui, time, os, subprocess
import pygetwindow as gw

pyautogui.FAILSAFE = False

# Launch Chrome fresh
os.system("taskkill /f /im chrome.exe >nul 2>&1")
time.sleep(3)

subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "https://chromewebstore.google.com/detail/metamask/nkbihfbeogaeaoehlefnkodbefgpgknn",
    "--no-first-run",
])
time.sleep(8)

# Find window
wins = gw.getWindowsWithTitle("Chrome")
chrome_win = None
for w in wins:
    try:
        if w.visible and w.width > 500:
            chrome_win = w
            break
    except:
        pass

if chrome_win:
    chrome_win.activate()
    time.sleep(2)
    
    # Take screenshot of the page area (below the URL bar)
    page_area = (chrome_win.left + 50, chrome_win.top + 100, chrome_win.width - 100, chrome_win.height - 150)
    screenshot = pyautogui.screenshot(region=page_area)
    screenshot.save("D:\\DDecentralized_AI_Agent\\page_screenshot.png")
    
    screen_w, screen_h = pyautogui.size()
    print(f"Screen: {screen_w}x{screen_h}", flush=True)
    print(f"Chrome window: {chrome_win.left},{chrome_win.top} {chrome_win.width}x{chrome_win.height}", flush=True)
    print(f"Screenshot saved to D:\\DDecentralized_AI_Agent\\page_screenshot.png", flush=True)
    
    # Try multiple click positions where "Add to Chrome" button might be
    # The button is in the header area, right side
    # Chrome Web Store header is about 56px tall
    # Try clicking at various positions
    positions = [
        (chrome_win.left + int(chrome_win.width * 0.85), chrome_win.top + 80),
        (chrome_win.left + int(chrome_win.width * 0.75), chrome_win.top + 100),
        (chrome_win.left + int(chrome_win.width * 0.8), chrome_win.top + 90),
        (chrome_win.left + int(chrome_win.width * 0.7), chrome_win.top + 110),
        (chrome_win.left + int(chrome_win.width * 0.9), chrome_win.top + 70),
    ]
    
    for i, (x, y) in enumerate(positions):
        print(f"Click {i}: ({x}, {y})", flush=True)
        pyautogui.click(x, y)
        time.sleep(1.5)
    
    # Now press Enter to accept the dialog (it should appear after clicking Add to Chrome)
    time.sleep(3)
    pyautogui.press("enter")
    print("Pressed Enter for dialog", flush=True)
    time.sleep(3)
    
    # Check if dialog appeared by pressing Tab+Tab+Enter
    pyautogui.press("tab")
    time.sleep(0.5)
    pyautogui.press("tab") 
    time.sleep(0.5)
    pyautogui.press("enter")
    print("Pressed Tab+Tab+Enter", flush=True)
    
    time.sleep(5)
    
    # Check installation
    import json
    prefs_path = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Default\Preferences"
    if os.path.exists(prefs_path):
        with open(prefs_path, encoding="utf-8") as f:
            prefs = json.load(f)
        exts = prefs.get("extensions", {}).get("settings", {})
        if "nkbihfbeogaeaoehlefnkodbefgpgknn" in exts:
            print("METAMASK INSTALLED!", flush=True)
        else:
            print("Not installed in Default profile", flush=True)
    
    # Also check Profile_Auto
    prefs_path2 = r"C:\Users\zafar\AppData\Local\Google\Chrome\User Data\Profile_Auto\Preferences"
    if os.path.exists(prefs_path2):
        with open(prefs_path2, encoding="utf-8") as f:
            prefs2 = json.load(f)
        exts2 = prefs2.get("extensions", {}).get("settings", {})
        if "nkbihfbeogaeaoehlefnkodbefgpgknn" in exts2:
            print("METAMASK INSTALLED in Profile_Auto!", flush=True)
        else:
            print("Not installed in Profile_Auto", flush=True)
else:
    print("Chrome window not found", flush=True)

input("Press Enter to close...")
