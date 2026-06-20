import pyautogui, time, subprocess, os
import pygetwindow as gw

# Kill Chrome first
os.system("taskkill /f /im chrome.exe >nul 2>&1")
time.sleep(3)

# Open Chrome to MetaMask install page
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
subprocess.Popen([
    chrome,
    "--profile-directory=Profile_Auto",
    "https://chromewebstore.google.com/detail/metamask/nkbihfbeogaeaoehlefnkodbefgpgknn",
    "--no-first-run",
])

time.sleep(8)

# Find Chrome window
wins = gw.getWindowsWithTitle("Chrome")
chrome_win = None
for w in wins:
    if w.visible:
        chrome_win = w
        break

if chrome_win:
    chrome_win.activate()
    time.sleep(1)
    print(f"Chrome window found at: {chrome_win.left},{chrome_win.top}", flush=True)
    
    # Click "Add to Chrome" button
    # The button is usually on the right side of the page
    # Screen coordinates: roughly center-right area
    screen_w, screen_h = pyautogui.size()
    print(f"Screen: {screen_w}x{screen_h}", flush=True)
    
    # Look for the button using image recognition
    # Or just click at the expected position
    # "Add to Chrome" button is typically at ~70% width, ~30% height of the page
    btn_x = chrome_win.left + int(chrome_win.width * 0.7)
    btn_y = chrome_win.top + int(chrome_win.height * 0.3)
    
    pyautogui.click(btn_x, btn_y)
    print(f"Clicked at {btn_x},{btn_y}", flush=True)
    time.sleep(3)
    
    # Click "Add extension" in the dialog
    # The dialog appears at the top center of the Chrome window
    dialog_x = chrome_win.left + int(chrome_win.width * 0.5)
    dialog_y = chrome_win.top + 80
    pyautogui.click(dialog_x, dialog_y)
    print(f"Clicked dialog at {dialog_x},{dialog_y}", flush=True)
    time.sleep(3)
    
    # Press Enter as fallback
    pyautogui.press("tab")
    time.sleep(0.5)
    pyautogui.press("tab")
    time.sleep(0.5)
    pyautogui.press("enter")
    print("Pressed Tab+Enter", flush=True)
    
    time.sleep(5)
    print("Done! MetaMask should be installed.", flush=True)
else:
    print("Chrome window not found!", flush=True)
    # Use absolute coordinates based on common screen resolution
    pyautogui.click(1400, 300)
    time.sleep(3)
    pyautogui.click(960, 100)
    time.sleep(2)
    pyautogui.press("tab")
    time.sleep(0.5)
    pyautogui.press("enter")
    print("Tried clicking at default positions", flush=True)

input("Press Enter to continue...")
