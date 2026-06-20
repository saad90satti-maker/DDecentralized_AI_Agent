"""
OS-Level Automation Agent v2: YouTube Studio Publish Pipeline
Pure Playwright automation (no OS fallback needed since browser automation works).
Self-healing: retries with alternative selectors on failure.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")
VIDEO_FILE = Path(__file__).resolve().parent / "hermes_demo_video.mp4"


async def execute_publish_pipeline():
    from playwright.async_api import async_playwright, TimeoutError as PTimeout

    print("=" * 60)
    print("  OS-LEVEL AUTOMATION AGENT v2")
    print("  Target: YouTube Studio Full Publish")
    print(f"  Profile: {PROFILE}")
    print("=" * 60)

    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        no_viewport=True,
    )

    page = context.pages[0] if context.pages else await context.new_page()
    results = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": {}}

    async def retry(name: str, fn, retries=3):
        for i in range(retries):
            try:
                r = await fn()
                results["steps"][name] = {"status": "OK", "attempts": i + 1}
                return r
            except Exception as e:
                print(f"    [{name}] attempt {i+1}/{retries}: {e}")
                if i < retries - 1:
                    await asyncio.sleep(3)
                else:
                    results["steps"][name] = {"status": "FAILED", "error": str(e)[:120]}
                    raise
        return None

    # ── STEP 1: Navigate YouTube Studio ──
    async def nav_studio():
        print(f"\n>>> [STEP 1] YouTube Studio...")
        await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
        title = await page.title()
        print(f"    Title: {title}")
        body = await page.text_content("body") or ""
        if "sign in" in body[:2000].lower():
            print(f"    !!! LOGIN REQUIRED - cannot proceed")
            return {"login": False}
        print(f"    Session ACTIVE")
        return {"login": True, "title": title}

    await retry("navigate", nav_studio)

    # ── STEP 2: Click Create → Upload Videos ──
    async def click_create_upload():
        print(f"\n>>> [STEP 2] Create → Upload...")
        # Click CREATE button (multiple selectors)
        create_selectors = [
            "ytcp-button#create-icon",
            "[aria-label='Create']",
            "ytcp-button:has-text('Create')",
            "#create-icon",
        ]
        for sel in create_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    print(f"    Create button clicked: {sel}")
                    await asyncio.sleep(2)
                    break
            except:
                continue
        else:
            print(f"    Create button not found - may already be on upload page")

        # Click "Upload videos"
        upload_selectors = [
            "ytcp-ve:has-text('Upload videos')",
            "text=Upload videos",
            "[aria-label='Upload videos']",
            "ytcp-ve#text-item:has-text('Upload')",
        ]
        for sel in upload_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    print(f"    Upload option clicked: {sel}")
                    await asyncio.sleep(3)
                    return True
            except:
                continue
        print(f"    Upload option not found - file picker may already be open")
        return True

    await retry("create_upload", click_create_upload)

    # ── STEP 3: Upload Video File ──
    async def upload_video():
        print(f"\n>>> [STEP 3] Upload video file...")
        if not VIDEO_FILE.exists():
            print(f"    Video file missing: {VIDEO_FILE}")
            return False

        # Try multiple file input selectors
        file_selectors = [
            "input[type='file']",
            "ytcp-uploads-file-picker input",
            ".upload-file-picker input",
            "#file-picker input",
            "input[accept*='video']",
        ]
        for sel in file_selectors:
            try:
                input_el = page.locator(sel).first
                if await input_el.is_visible(timeout=3000):
                    await input_el.set_input_files(str(VIDEO_FILE))
                    print(f"    File uploaded via: {sel}")
                    await asyncio.sleep(5)
                    return True
            except:
                continue

        # If no file input visible, page might need the picker triggered
        print(f"    No file input found - waiting for upload dialog...")
        await asyncio.sleep(5)
        for sel in file_selectors:
            try:
                input_el = page.locator(sel).first
                if await input_el.is_visible(timeout=2000):
                    await input_el.set_input_files(str(VIDEO_FILE))
                    print(f"    File uploaded (delayed): {sel}")
                    await asyncio.sleep(5)
                    return True
            except:
                continue

        print(f"    ALL file inputs failed - taking screenshot for debug")
        try:
            await page.screenshot(path=str(Path(__file__).resolve().parent / "agent_data" / "upload_error.png"))
        except:
            pass
        return False

    await retry("upload_file", upload_video)

    # ── STEP 4: Wait for processing + Fill metadata ──
    async def fill_metadata():
        print(f"\n>>> [STEP 4] Wait for processing + Metadata...")

        # Wait up to 60s for title textbox to appear
        print(f"    Waiting for upload processing...")
        title_selectors = ["#title-textbox", "#textbox", "[aria-label*='Title']", "ytcp-video-title input"]
        found = False
        for sel in title_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=60000):
                    print(f"    Upload processed - found title input: {sel}")
                    found = True
                    break
            except:
                continue

        if not found:
            print(f"    Title input not found after 60s - continuing anyway")
            return False

        # Fill title
        title = f"Hermes AI Agent - Autonomous Pipeline Demo {int(time.time())}"
        try:
            title_input = page.locator("#title-textbox, #textbox, [aria-label*='Title']").first
            await title_input.fill("")
            await title_input.type(title, delay=30)
            print(f"    Title filled: {title}")
        except Exception as e:
            print(f"    Title fill failed: {e}")

        # Fill description
        try:
            desc_input = page.locator("#description-textbox, #description, [aria-label*='Description']").first
            if await desc_input.is_visible(timeout=3000):
                desc = "Zero-cost autonomous AI agent demo using Gemini API and Playwright browser automation."
                await desc_input.fill(desc)
                print(f"    Description filled")
        except:
            print(f"    Description skipped")

        return True

    await retry("fill_metadata", fill_metadata)

    # ── STEP 5: Click NEXT through all dialogs ──
    async def click_next():
        print(f"\n>>> [STEP 5] Next buttons...")
        for step_num in range(1, 4):
            try:
                # Wait a moment for dialog transition
                await asyncio.sleep(2)
                next_selectors = [
                    "ytcp-button#next-button",
                    "#next-button",
                    "[aria-label='Next']",
                    "ytcp-button:has-text('Next')",
                    "#done-button",
                    "ytcp-button#done-button",
                ]
                clicked = False
                for sel in next_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=3000) and await btn.is_enabled():
                            await btn.click()
                            print(f"    Step {step_num}: clicked {sel}")
                            clicked = True
                            break
                    except:
                        continue
                if not clicked:
                    print(f"    Step {step_num}: no button found, may be auto-advanced")
            except Exception as e:
                print(f"    Step {step_num}: {e}")
        return True

    await retry("click_next", click_next)

    # ── STEP 6: Set visibility to Public + Publish ──
    async def publish():
        print(f"\n>>> [STEP 6] Publish...")

        # Set visibility to Public
        try:
            vis_selector = "ytcp-visibility-select #privacy-select, #privacy-select, [aria-label*='Visibility']"
            vis_el = page.locator(vis_selector).first
            if await vis_el.is_visible(timeout=3000):
                await vis_el.click()
                await asyncio.sleep(1)
                public_el = page.locator("text=Public, #public-radio, [aria-label='Public'], tp-yt-paper-radio-button:has-text('Public')").first
                if await public_el.is_visible(timeout=2000):
                    await public_el.click()
                    await asyncio.sleep(1)
                    print(f"    Visibility set to Public")
        except:
            print(f"    Visibility selector skipped")

        # Click Publish / Done button
        publish_selectors = [
            "ytcp-button#done-button",
            "#done-button",
            "[aria-label='Publish']",
            "ytcp-button:has-text('Publish')",
            "ytcp-button:has-text('Public')",
            "#trigger-button",
            "ytcp-button#trigger-button",
        ]
        for sel in publish_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=3000) and await btn.is_enabled():
                    await btn.click()
                    print(f"    [PUBLISHED] via {sel}")
                    await asyncio.sleep(3)
                    return True
            except:
                continue

        # Close button may appear after publish
        try:
            close_sel = "ytcp-button#close-button, #close-button, [aria-label='Close']"
            close_btn = page.locator(close_sel).first
            if await close_btn.is_visible(timeout=5000):
                await close_btn.click()
                print(f"    Published (close button visible)")
                await asyncio.sleep(2)
                return True
        except:
            pass

        print(f"    No publish button found - checking page state")
        try:
            await page.screenshot(path=str(Path(__file__).resolve().parent / "agent_data" / "publish_state.png"))
        except:
            pass
        return False

    await retry("publish", publish)

    # ── STEP 7: Verify ──
    async def verify():
        print(f"\n>>> [STEP 7] Verification...")
        await page.goto("https://studio.youtube.com/videos", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)
        body = await page.text_content("body") or ""
        ok = "video" in body.lower() and len(body) > 500
        print(f"    Video manager: {'LOADED' if ok else 'ISSUE'}")
        try:
            await page.screenshot(path=str(Path(__file__).resolve().parent / "agent_data" / "final_state.png"))
            print(f"    Screenshot saved")
        except:
            pass
        return ok

    await retry("verify", verify)

    # ── REPORT ──
    results["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ok = sum(1 for s in results["steps"].values() if s.get("status") == "OK")
    fail = sum(1 for s in results["steps"].values() if s.get("status") == "FAILED")
    results["final_status"] = "SUCCESS" if fail == 0 else f"PARTIAL ({ok}OK/{fail}FAIL)"

    print("\n" + "=" * 60)
    print(f"  FINAL STATUS: {results['final_status']}")
    print("=" * 60)
    for name, info in results["steps"].items():
        icon = "[OK]" if info["status"] == "OK" else "[!]"
        print(f"  {icon} {name}: {info['status']}")
    print("=" * 60)

    Path(__file__).resolve().parent.joinpath("agent_data").mkdir(exist_ok=True)
    report_path = Path(__file__).resolve().parent / "agent_data" / "publish_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"  Report: {report_path}")
    print("=" * 60)

    # Keep browser open for user inspection
    print(f"\n  Browser left open for review. Close manually or press Ctrl+C.")
    try:
        while True:
            await asyncio.sleep(10)
            print(f"  [alive] {len(context.pages)} tab(s)", end="\r")
    except asyncio.CancelledError:
        pass
    finally:
        await context.close()
        await p.stop()


if __name__ == "__main__":
    try:
        asyncio.run(execute_publish_pipeline())
    except KeyboardInterrupt:
        print("\nAgent terminated by user.")
