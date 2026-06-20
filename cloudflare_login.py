"""Go to Cloudflare and login"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="C:\\Users\\zafar\\AppData\\Local\\Google\\Chrome\\User Data\\Default",
            headless=False,
            args=["--window-position=0,0"],
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        await page.goto("https://dash.cloudflare.com", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # Check if already logged in
        if "login" in page.url.lower() or "signin" in page.url.lower():
            print("Login page detected. Please log in manually.")
            input("Press Enter after logging in...")
            await asyncio.sleep(3)

        print(f"Current URL: {page.url[:80]}")
        print("Cloudflare dashboard loaded")
        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\cloudflare.png")
        print("Screenshot saved")

        input("Press Enter to close...")
        await ctx.close()
        await p.stop()

asyncio.run(main())
