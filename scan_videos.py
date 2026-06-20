"""Scan YouTube Studio video manager for video list elements"""
import asyncio
from playwright.async_api import async_playwright
import json

async def scan():
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir="C:\\Users\\zafar\\AppData\\Local\\Google\\Chrome\\User Data\\Default",
        headless=False,
        args=["--window-position=0,0"],
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    await page.goto("https://studio.youtube.com/videos", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)

    # Check what the video list area looks like
    scan_result = await page.evaluate("""() => {
        // Find the main content area
        const main = document.querySelector('#content-container, #main-panel, ytcp-video-manager');
        const result = {};

        // Check for video-related elements
        result.video_rows = document.querySelectorAll('ytcp-video-row').length;
        result.video_cards = document.querySelectorAll('ytcp-video-card').length;
        result.table_rows = document.querySelectorAll('ytcp-table-row, tr[is], .video-row').length;

        // Scan all custom elements
        const all = document.querySelectorAll('*');
        const custom_tags = new Set();
        const ids = new Set();
        const classes = new Set();
        for (const el of all) {
            const tag = el.tagName.toLowerCase();
            if (tag.includes('-')) custom_tags.add(tag);
            if (el.id) ids.add(el.id);
        }

        // Get text content of main area
        const main_text = main ? main.textContent.slice(0, 1000) : '(no main)';

        // Get visible text snippets
        const texts = [];
        for (const el of all) {
            if (el.offsetParent !== null && el.children.length === 0 && el.textContent.trim()) {
                texts.push(el.textContent.trim().slice(0, 40));
                if (texts.length > 30) break;
            }
        }

        return {
            video_rows: result.video_rows,
            video_cards: result.video_cards,
            table_rows: result.table_rows,
            custom_tags: Array.from(custom_tags).slice(0, 30),
            ids: Array.from(ids).slice(0, 20),
            classes: Array.from(classes).slice(0, 10),
            texts: texts,
        };
    }""")

    print("=== Page Structure ===")
    print(f"Video rows (ytcp-video-row): {scan_result['video_rows']}")
    print(f"Video cards (ytcp-video-card): {scan_result['video_cards']}")
    print(f"Table rows: {scan_result['table_rows']}")
    print(f"\nCustom elements: {json.dumps(scan_result['custom_tags'], indent=2)}")
    print(f"\nIDs: {json.dumps(scan_result['ids'], indent=2)}")
    print(f"\nVisible texts:")
    for t in scan_result['texts']:
        print(f"  {t}")

    await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\video_manager.png")
    print("\nScreenshot saved")

    await ctx.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(scan())
