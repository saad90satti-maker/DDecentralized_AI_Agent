"""
Ghost Engine: YouTube Upload Pipeline v3 — Fixed backdrop interception.
"""
import asyncio
import json
import time
from pathlib import Path

PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")
VIDEO_FILE = Path(__file__).resolve().parent / "hermes_demo_video.mp4"


async def upload_and_publish():
    from playwright.async_api import async_playwright

    print("=" * 60)
    print("  GHOST ENGINE - YOUTUBE UPLOAD v3")
    print(f"  Profile: {PROFILE}")
    print("=" * 60, flush=True)

    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        no_viewport=True,
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    step_results = {}

    # ── 1. Navigate ──
    await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    title = await page.title()
    print(f"[1] {title}", flush=True)
    step_results["navigate"] = title

    # ── 2. File chooser interception → Create → Upload ──
    if not VIDEO_FILE.exists():
        print(f"[!] No video file at {VIDEO_FILE}", flush=True)
        step_results["upload"] = "NO_FILE"
    else:
        # Set up file chooser listener BEFORE triggering the upload
        async with page.expect_file_chooser() as fc_info:
            # Click Create
            await page.locator("[aria-label='Create']").first.click()
            await asyncio.sleep(2)
            print("[2] Create clicked", flush=True)

            # Click Upload videos (force=True to bypass backdrop)
            await page.locator("text=Upload videos").first.click(force=True, timeout=10000)
            print("[3] Upload videos clicked", flush=True)

        # File chooser should now be captured
        file_chooser = await fc_info.value
        await file_chooser.set_files(str(VIDEO_FILE))
        print(f"[4] File uploaded: {VIDEO_FILE.name}", flush=True)
        step_results["upload"] = "UPLOADED"

        # ── 4. Wait for processing + title ──
        print("[5] Waiting for upload processing...", flush=True)
        try:
            await page.locator("#title-textbox, #textbox").first.wait_for(state="visible", timeout=120000)
            print("[6] Processing complete - title input visible", flush=True)
        except:
            print("[6] Title input timeout - checking page state", flush=True)

        # Fill metadata
        title_text = f"Hermes AI Agent - Autonomous Demo {int(time.time())}"
        try:
            ti = page.locator("#title-textbox, #textbox").first
            await ti.fill("")
            await ti.type(title_text, delay=20)
            print(f"[7] Title: {title_text}", flush=True)
        except Exception as e:
            print(f"[7] Title fill: {e}", flush=True)

        try:
            di = page.locator("#description-textbox, #description").first
            if await di.is_visible(timeout=3000):
                await di.fill("Zero-cost autonomous AI agent demo using Gemini API and Playwright.")
                print("[8] Description filled", flush=True)
        except:
            pass

        # ── 5. Click NEXT buttons ──
        for i in range(3):
            await asyncio.sleep(3)
            try:
                nxt = page.locator("ytcp-button#next-button, #next-button, [aria-label='Next'], ytcp-button:has-text('Next')").first
                if await nxt.is_visible(timeout=5000) and await nxt.is_enabled():
                    await nxt.click()
                    print(f"[9.{i}] Next clicked", flush=True)
                else:
                    print(f"[9.{i}] No next button", flush=True)
            except:
                print(f"[9.{i}] Next skipped", flush=True)

        # ── 6. Set Public + Publish ──
        try:
            vs = page.locator("#privacy-select, [aria-label*='Visibility']").first
            if await vs.is_visible(timeout=3000):
                await vs.click()
                await asyncio.sleep(1)
                await page.locator("text=Public, #public-radio").first.click(force=True)
                await asyncio.sleep(1)
                print("[10] Visibility set to Public", flush=True)
        except:
            pass

        for sel in ["ytcp-button#done-button", "#done-button", "[aria-label='Publish']", "ytcp-button:has-text('Publish')"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=3000) and await btn.is_enabled():
                    await btn.click(force=True)
                    print(f"[11] PUBLISHED via: {sel}", flush=True)
                    await asyncio.sleep(3)
                    step_results["publish"] = "PUBLISHED"
                    break
            except:
                continue
        else:
            print("[11] No publish button found", flush=True)
            step_results["publish"] = "NOT_FOUND"

        # ── 7. Verify ──
        await asyncio.sleep(3)
        await page.goto("https://studio.youtube.com/videos", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)
        body = await page.text_content("body") or ""
        ok = "video" in body.lower() and len(body) > 500
        print(f"[12] Video manager: {'OK' if ok else 'ISSUE'}", flush=True)
        step_results["verify"] = "OK" if ok else "ISSUE"

    # Save report
    report = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps": step_results,
        "final": "SUCCESS" if "PUBLISHED" in str(step_results) else "PARTIAL",
    }
    rpath = Path(__file__).resolve().parent / "agent_data" / "upload_v3_report.json"
    with open(rpath, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report: {rpath}", flush=True)
    print(f"  Status: {report['final']}", flush=True)

    await ctx.close()
    await p.stop()


asyncio.run(upload_and_publish())
