"""Launch Chrome with CDP + MetaMask + real profile cookies"""
import subprocess, time, asyncio, json, os, shutil, sqlite3, sys
from pathlib import Path
from playwright.async_api import async_playwright

CHROME = os.getenv("CHROME_PATH", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" if sys.platform == "win32" else "/usr/bin/google-chrome")
REAL_DATA = os.getenv("CHROME_USER_DATA", os.path.expanduser("~/AppData/Local/Google/Chrome/User Data") if sys.platform == "win32" else os.path.expanduser("~/.config/google-chrome"))
MM_EXT_ID = "nkbihfbeogaeaoehlefnkodbefgpgknn"
TEMP_DIR = os.getenv("TEMP", "/tmp") + "/mm_cdp"

async def main():
    # Clean temp
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(f"{TEMP_DIR}\\Default")

    # Copy local storage and extension data for MetaMask
    mm_local = os.path.join(REAL_DATA, "Default", "Local Extension Settings", MM_EXT_ID)
    mm_sync = os.path.join(REAL_DATA, "Default", "Sync Extension Settings", MM_EXT_ID)
    for src in [mm_local, mm_sync]:
        if os.path.exists(src):
            dest = os.path.join(TEMP_DIR, "Default", "Local Extension Settings", MM_EXT_ID)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copytree(src, dest, dirs_exist_ok=True)

    # Kill Chrome
    print("1. Killing Chrome...")
    subprocess.run("taskkill /f /im chrome.exe 2>nul", shell=True)
    await asyncio.sleep(4)

    print("2. Launching with MetaMask loaded...")
    proc = subprocess.Popen([
        CHROME,
        f"--user-data-dir={TEMP_DIR}",
        f"--disable-extensions-except={MM_PATH}",
        f"--load-extension={MM_PATH}",
        "--remote-debugging-port=49222",
        "--no-first-run",
        "--no-default-browser-check",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    await asyncio.sleep(10)

    # Verify port
    netstat = subprocess.run("netstat -an | findstr 49222", shell=True, capture_output=True, text=True)
    if not netstat.stdout.strip():
        print("   Port NOT open - aborting")
        return

    print("3. Connecting via CDP...")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:49222")
        ctx = browser.contexts[0]
        page = ctx.pages[0]

        await page.goto("https://example.com")
        await asyncio.sleep(5)

        has_eth = await page.evaluate("() => !!window.ethereum")
        print(f"4. window.ethereum: {has_eth}")

        if has_eth:
            info = await page.evaluate("""() => ({
                isMetaMask: window.ethereum?.isMetaMask,
                selectedAddress: window.ethereum?.selectedAddress,
                chainId: window.ethereum?.chainId,
            })""")
            print(f"   {json.dumps(info, indent=2)}")
        else:
            print("   MetaMask not injecting. Extensions page:")
            ext_page = await ctx.new_page()
            await ext_page.goto("chrome://extensions/")
            await asyncio.sleep(3)
            ext_text = await ext_page.text_content("body") or ""
            mm_found = "nkbihfbeogaeaoehlefnkodbefgpgknn" in ext_text
            print(f"   MetaMask in extensions list: {mm_found}")
            if "extensions" in ext_text.lower():
                print(f"   Extensions page shows content")

        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\metamask_cdp2.png")
        print("5. Screenshot saved. Chrome stays open.")

asyncio.run(main())
