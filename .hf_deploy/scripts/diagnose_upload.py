"""Diagnose YouTube upload dialog state - find why file input isn't visible."""
import asyncio
from pathlib import Path

PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")
VIDEO = Path(__file__).resolve().parent.parent / "hermes_demo_video.mp4"


async def diagnose():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox"], no_viewport=True
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    print(f"Page title: {await page.title()}", flush=True)

    # Click Create
    await page.locator("[aria-label='Create']").first.click()
    await asyncio.sleep(2)

    # Click Upload videos
    await page.locator("text=Upload videos").first.click()
    await asyncio.sleep(4)

    # Diagnose
    inputs = await page.locator("input").all()
    print(f"Total inputs: {len(inputs)}", flush=True)
    for inp in inputs:
        tp = await inp.get_attribute("type")
        accept = await inp.get_attribute("accept")
        visible = await inp.is_visible()
        rid = await inp.get_attribute("id")
        print(f"  type={tp} accept={accept} visible={visible} id={rid}", flush=True)

    # Check all iframes
    frames = page.frames
    print(f"Frames: {len(frames)}", flush=True)
    for i, f in enumerate(frames):
        url = f.url[:80]
        print(f"  Frame {i}: {url}", flush=True)
        finputs = await f.locator("input").all()
        for inp in finputs:
            tp = await inp.get_attribute("type")
            if tp == "file":
                print(f"    FILE INPUT in frame {i}!", flush=True)

    html_preview = (await page.content())[:3000]
    # Check for upload dialog presence
    if 'ytcp-uploads-dialog' in html_preview or 'ytcp-uploads' in html_preview:
        print("Upload dialog detected!", flush=True)
    else:
        print("No upload dialog in HTML", flush=True)

    # Try clicking the upload area directly
    try:
        upload_area = page.locator("#upload-area, .upload-area, [drag-drop], ytcp-uploads-file-picker").first
        if await upload_area.is_visible(timeout=3000):
            print("Upload area visible - clicking", flush=True)
            await upload_area.click()
            await asyncio.sleep(2)
    except Exception as e:
        print(f"Upload area click: {e}", flush=True)

    await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\upload_diag.png")
    print("Screenshot: agent_data/upload_diag.png", flush=True)
    await ctx.close()
    await p.stop()


asyncio.run(diagnose())
