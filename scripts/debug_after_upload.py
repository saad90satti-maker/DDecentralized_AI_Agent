"""Debug YouTube Studio state after v5 upload."""
import asyncio
from pathlib import Path

PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")


async def debug():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox"], no_viewport=True
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    await page.goto("https://studio.youtube.com/videos",
                    wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    print(f"Videos page: {await page.title()}", flush=True)

    # Scan all visible buttons and their text
    button_info = await page.evaluate("""() => {
        const all = document.querySelectorAll('button, ytcp-button, [role="button"], .ytcp-button, tp-yt-paper-button');
        return Array.from(all).map(b => ({
            text: (b.textContent || '').trim().slice(0, 40),
            visible: b.offsetParent !== null,
            tag: b.tagName,
            id: b.id,
            ariaLabel: b.getAttribute('aria-label') || '',
            class: (b.className || '').slice(0, 30),
        })).filter(b => b.visible);
    }""")
    print(f"\nVisible buttons ({len(button_info)}):", flush=True)
    for b in button_info:
        print(f"  [{b['tag']}#{b['id']}] '{b['text']}' aria={b['ariaLabel']}", flush=True)

    # Check for any upload dialog
    dialog_info = await page.evaluate("""() => {
        const dialogs = document.querySelectorAll('ytcp-uploads-dialog, ytcp-video-edit, ytcp-dialog, tp-yt-paper-dialog');
        return Array.from(dialogs).map(d => ({
            tag: d.tagName,
            id: d.id,
            visible: d.offsetParent !== null,
            text: (d.textContent || '').trim().slice(0, 100),
        }));
    }""")
    print(f"\nDialogs ({len(dialog_info)}):", flush=True)
    for d in dialog_info:
        print(f"  [{d['tag']}#{d['id']}] visible={d['visible']} text='{d['text']}'", flush=True)

    await page.screenshot(path="D:/DDecentralized_AI_Agent/agent_data/debug_after_upload.png")
    print("\nScreenshot saved", flush=True)
    await ctx.close()
    await p.stop()


asyncio.run(debug())
