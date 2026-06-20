"""Check for uploaded video status after dialog close."""
import asyncio
from pathlib import Path
PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")


async def check_status():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox"], no_viewport=True
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    await page.goto("https://studio.youtube.com/videos",
                    wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(10)  # extra time for video list to render

    # Close any dialogs
    await page.evaluate("""() => {
        document.querySelectorAll('[aria-label="Close"], #close-button, ytcp-button').forEach(el => el.click());
    }""")
    await asyncio.sleep(3)

    # Get all video-like elements
    all_video_elements = await page.evaluate("""() => {
        const selectors = ['ytcp-video-row', 'ytcp-video-item', '.video-list-item', 'tr', '[role="row"]'];
        return selectors.map(sel => {
            const els = document.querySelectorAll(sel);
            return Array.from(els).slice(0, 10).map(el => ({
                sel: sel,
                text: (el.textContent || '').trim().slice(0, 80),
                visible: el.offsetParent !== null,
            }));
        }).flat().filter(x => x.visible);
    }""")
    print(f"Visible video elements: {len(all_video_elements)}", flush=True)
    for v in all_video_elements:
        print(f"  [{v['sel']}] '{v['text']}'", flush=True)

    # Check for any content
    body = await page.text_content("body") or ""
    if "video" in body.lower():
        # Find video titles
        titles = await page.evaluate("""() => {
            const all = document.querySelectorAll('[id*="title"], [class*="title"], a');
            return Array.from(all).filter(el => el.offsetParent !== null && el.textContent.trim())
                .slice(0, 20)
                .map(el => el.textContent.trim().slice(0, 60));
        }""")
        print(f"\nVisible titles:", flush=True)
        for t in titles:
            print(f"  '{t}'", flush=True)
    else:
        print("No 'video' keyword in body", flush=True)
        print(f"Body length: {len(body)}", flush=True)

    # Check if we're on a different page
    print(f"\nURL: {page.url}", flush=True)
    print(f"Title: {await page.title()}", flush=True)

    await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\status_check.png")
    print("\nScreenshot saved", flush=True)
    await ctx.close()
    await p.stop()


asyncio.run(check_status())
