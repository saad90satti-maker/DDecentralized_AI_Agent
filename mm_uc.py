import undetected_chromedriver as uc
import time, os, json

PROFILE_DIR = os.getenv("BROWSER_USER_DATA_DIR", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data"))
EXT_PATH = os.getenv("METAMASK_EXT_PATH", os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\User Data\Profile_Auto\Extensions\nkbihfbeogaeaoehlefnkodbefgpgknn\13.35.1.0_0"))
EXT_ID = os.getenv("METAMASK_EXT_ID", "nkbihfbeogaeaoehlefnkodbefgpgknn")
MM_PASS = os.getenv("METAMASK_PASSWORD", "")

os.system("taskkill /f /im chrome.exe >nul 2>&1")
time.sleep(3)

options = uc.ChromeOptions()
options.add_argument(f"--user-data-dir={PROFILE_DIR}")
options.add_argument("--profile-directory=Profile_Auto")
options.add_argument(f"--load-extension={EXT_PATH}")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--no-first-run")
options.add_argument("--no-default-browser-check")

print("Launching Chrome with MetaMask via undetected_chromedriver...", flush=True)
driver = uc.Chrome(options=options)
time.sleep(8)

print("Chrome launched!", flush=True)

# Try to open MetaMask
mm_url = f"chrome-extension://{EXT_ID}/home.html"
print(f"Opening: {mm_url}", flush=True)

try:
    driver.get(mm_url)
    time.sleep(5)
    print(f"Title: {driver.title}", flush=True)
    print(f"URL: {driver.current_url[:120]}", flush=True)
    body = driver.find_element("tag name", "body").text[:3000]
    print(f"Body:\n{body}", flush=True)
    
    # Check for unlock/password page
    if "unlock" in body.lower() or "password" in body.lower():
        print("\nUNLOCK PAGE - entering password...", flush=True)
        try:
            pw_input = driver.find_element("css selector", "input[type='password']")
            pw_input.send_keys(MM_PASS)
            time.sleep(1)
            unlock_btn = driver.find_element("xpath", "//button[contains(text(),'Unlock')]")
            unlock_btn.click()
            print("Clicked Unlock", flush=True)
            time.sleep(5)
            body2 = driver.find_element("tag name", "body").text[:1000]
            print(f"After unlock: {body2}", flush=True)
        except Exception as e:
            print(f"Could not unlock: {e}", flush=True)
    
    driver.save_screenshot("D:\\DDecentralized_AI_Agent\\metamask.png")
    print("Screenshot saved!", flush=True)
    
except Exception as e:
    print(f"Failed: {e}", flush=True)

time.sleep(10)
driver.quit()
