"""
Ghost Engine: Complete the publish from video manager.
Closes any leftover dialogs, navigates to video list, publishes draft videos.
"""
import asyncio
import json
import time
from pathlib import Path

PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")


async def complete_publish():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox"], no_viewport=True
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    report = {}

    # Step 1: Navigate and close any dialogs
    await page.goto("https://studio.youtube.com/videos",
                    wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)

    # Close any dialogs
    close_count = await page.evaluate("""() => {
        let count = 0;
        document.querySelectorAll('[aria-label="Close"], #close-button, ytcp-button#close-button, tp-yt-paper-dialog ytcp-button').forEach(el => {
            el.click();
            count++;
        });
        return count;
    }""")
    print(f"Closed {close_count} dialog(s)", flush=True)
    await asyncio.sleep(2)

    # Step 2: Find the latest video in draft status
    print("\nScanning videos...", flush=True)
    videos = await page.evaluate("""() => {
        const rows = document.querySelectorAll('ytcp-video-row');
        return Array.from(rows).slice(0, 5).map(r => ({
            title: (r.querySelector('#video-title, a, .video-title') || {}).textContent || '',
            status: (r.querySelector('.status, [id*=status]') || {}).textContent || '',
            visible: r.offsetParent !== null,
        }));
    }""")
    print(f"Videos found: {len(videos)}", flush=True)
    for v in videos:
        print(f"  '{v['title'][:50]}' status='{v['status']}' visible={v['visible']}", flush=True)

    # Step 3: Look for the video by title
    target_title = "Hermes AI Agent"
    for v in videos:
        if target_title.lower() in v["title"].lower():
            print(f"\nFound target video! Status: {v['status']}", flush=True)
            if "draft" in v["status"].lower() or "uploaded" in v["status"].lower():
                print("Video is unpublished. Attempting to publish...", flush=True)

                # Click on the video to edit
                rows = page.locator("ytcp-video-row").all()
                for row in await rows:
                    title_el = row.locator("#video-title, a").first
                    t = await title_el.text_content() or ""
                    if target_title.lower() in t.lower():
                        await row.click()
                        await asyncio.sleep(3)
                        print("  Video clicked for editing", flush=True)
                        break

                # Look for visibility publish
                await asyncio.sleep(3)
                vis = page.locator("#privacy-select, [aria-label*='Visibility']").first
                if await vis.is_visible(timeout=5000):
                    await vis.click()
                    await asyncio.sleep(1)
                    pub = page.locator("text=Public").first
                    if await pub.is_visible(timeout=3000):
                        await pub.click()
                        print("  Set to Public", flush=True)
                        await asyncio.sleep(1)

                # Click Save/Publish
                for sel in ["ytcp-button#done-button", "#done-button",
                            "[aria-label='Publish']", "ytcp-button:has-text('Save')",
                            "ytcp-button:has-text('Publish')"]:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=3000) and await btn.is_enabled():
                        await btn.click()
                        print(f"  PUBLISHED via: {sel}", flush=True)
                        report["publish"] = "PUBLISHED"
                        break
                else:
                    print("  No publish button found in editor", flush=True)
            break
    else:
        print(f"\nNo video found with title '{target_title}'", flush=True)

    await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\publish_final.png")
    print(f"\nScreenshot saved", flush=True)

    report["status"] = "completed"
    rp = Path(__file__).resolve().parent / "agent_data" / "publish_complete.json"
    with open(rp, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {rp}", flush=True)

    await ctx.close()
    await p.stop()


asyncio.run(complete_publish())
