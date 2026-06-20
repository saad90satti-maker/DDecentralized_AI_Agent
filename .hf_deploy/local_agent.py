import asyncio, sys, os, subprocess, time, shutil
from playwright.async_api import async_playwright

def detect_profile():
    if sys.platform == "win32":
        return os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:
        return os.path.expanduser("~/.config/google-chrome")

TEMP_DIR = os.path.join(os.environ.get("TEMP", "."), "playwright_local_agent")

async def main():
    real_user_data = detect_profile()
    src_default = os.path.join(real_user_data, "Default")
    dst_default = os.path.join(TEMP_DIR, "Default")

    print(f"[agent] Real: {real_user_data}")
    print(f"[agent] Temp: {TEMP_DIR}")

    print("[agent] Killing Chrome ...")
    if sys.platform == "win32":
        subprocess.run("taskkill /f /im chrome.exe 2>nul", shell=True)
    else:
        subprocess.run("pkill -f chrome 2>/dev/null", shell=True)
    await asyncio.sleep(3)

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(dst_default, exist_ok=True)

    # Copy session files to preserve login state
    for name in ["Cookies", "Cookies-journal", "Login Data", "Login Data-journal",
                 "Bookmarks", "Bookmarks.bak", "Favicons", "Favicons-journal",
                 "History", "History-journal", "Top Sites", "Top Sites-journal"]:
        s = os.path.join(src_default, name)
        d = os.path.join(dst_default, name)
        if os.path.isfile(s):
            try: shutil.copy2(s, d)
            except: pass

    for ls_name in ["Local Storage", "Session Storage"]:
        s = os.path.join(src_default, ls_name)
        d = os.path.join(dst_default, ls_name)
        if os.path.isdir(s):
            try:
                shutil.copytree(s, d, dirs_exist_ok=True)
            except: pass

    print("[agent] Profile data copied (sessions preserved)")

    print("[agent] Launching browser ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=TEMP_DIR,
            headless=False,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--window-position=0,0",
                "--window-size=1400,900",
            ],
        )

        pages = browser.pages
        page = pages[0] if pages else await browser.new_page()

        print("[agent] Opening YouTube ...")
        await page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        print(f"[agent] YouTube: {page.url}")

        print("[agent] Opening Gmail ...")
        tab2 = await browser.new_page()
        await tab2.goto("https://mail.google.com/mail/u/0/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        print("\n[agent] === READY ===")
        print("[agent] Browser open. Sessions restored from real profile.")
        print("[agent] Keep this terminal open to keep the browser alive.\n")

        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass
        finally:
            print("[agent] Closing ...")
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
