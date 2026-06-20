"""Quick diagnostic: check upload dialog state and take screenshot"""
import asyncio
from playwright.async_api import async_playwright
import json
from pathlib import Path

async def check():
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir="C:\\Users\\zafar\\AppData\\Local\\Google\\Chrome\\User Data\\Default",
        headless=False,
        args=["--window-position=0,0"],
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    
    print("Navigating to YouTube Studio...")
    await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    
    # Check if upload dialog is open
    has_dialog = await page.evaluate("""() => {
        return {
            dialog: !!document.querySelector('ytcp-uploads-dialog'),
            next: !!document.querySelector('#next-button'),
            title: !!(document.querySelector('#title-textbox, #textbox')),
        };
    }""")
    print(f"Dialog state: {json.dumps(has_dialog)}")
    
    if has_dialog["dialog"]:
        diag_text = await page.evaluate("""() => {
            const d = document.querySelector('ytcp-uploads-dialog');
            if (!d) return '';
            // Get all visible text content, removing extra whitespace
            const walker = document.createTreeWalker(d, NodeFilter.SHOW_TEXT, null, false);
            let texts = [];
            let node;
            while (node = walker.nextNode()) {
                const t = node.textContent.trim();
                if (t && node.offsetParent !== null) texts.push(t);
            }
            return texts.join(' | ').slice(0, 3000);
        }""")
        print(f"\nDialog visible text:\n  {diag_text}")
        
        # Check next button
        nxt_state = await page.evaluate("""() => {
            const nxt = document.querySelector('#next-button');
            if (!nxt) return {exists: false};
            return {
                exists: true,
                tag: nxt.tagName,
                hidden: nxt.hidden,
                disabled: nxt.disabled,
                aria_disabled: nxt.getAttribute('aria-disabled'),
                classes: nxt.className,
                outer: nxt.outerHTML.slice(0, 300),
            };
        }""")
        print(f"\nNext button:\n  {json.dumps(nxt_state, indent=2)}")
        
        # Check for any processing indicators
        processing = await page.evaluate("""() => {
            const indicators = document.querySelectorAll(
                'paper-progress, [role="progressbar"], [class*="processing"], ' +
                'ytcp-video-progress-bar, paper-spinner, ' +
                'ytcp-circular-progress, [class*="spinner"]'
            );
            return Array.from(indicators).map(el => ({
                tag: el.tagName,
                id: el.id,
                class: (el.className || '').slice(0, 40),
                visible: el.offsetParent !== null,
                hidden: el.hidden,
            }));
        }""")
        print(f"\nProcessing indicators:\n  {json.dumps(processing, indent=2)}")
        
        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\dialog_state.png")
        print(f"\nScreenshot saved to dialog_state.png")
    else:
        print("No upload dialog open")
        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\studio_state.png")
        print("Screenshot saved to studio_state.png")
    
    await ctx.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(check())
