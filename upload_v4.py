"""
Ghost Engine: YouTube Upload v4 — Direct hidden file input manipulation.
"""
import asyncio
import json
import time
from pathlib import Path

PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")
VIDEO_FILE = Path(__file__).resolve().parent / "hermes_demo_video.mp4"


async def upload_v4():
    from playwright.async_api import async_playwright

    print("=" * 60, flush=True)
    print("  GHOST ENGINE - YOUTUBE UPLOAD v4", flush=True)
    print("=" * 60, flush=True)

    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        no_viewport=True,
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    results = {}

    # Step 1: Navigate
    await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    print(f"[1] {await page.title()}", flush=True)

    # Step 2: Click Create, then Upload with file chooser interception
    print("[2] Clicking Create...", flush=True)
    await page.locator("[aria-label='Create']").first.click(force=True)
    await asyncio.sleep(2)

    print("[3] Clicking Upload videos + file chooser...", flush=True)
    file_uploaded = False
    if VIDEO_FILE.exists():
        async with page.expect_file_chooser() as fc_info:
            # Use the ytcp-ve selector that has the proper click handler
            upload_btn = page.locator("ytcp-ve:has-text('Upload videos')").first
            if await upload_btn.is_visible(timeout=3000):
                await upload_btn.click(force=True)
                print(f"  Upload button clicked (ytcp-ve)", flush=True)
            else:
                # Fallback to text selector
                await page.locator("text=Upload videos").first.click(force=True, timeout=5000)

        # File chooser should be captured
        file_chooser = await fc_info.value
        await file_chooser.set_files(str(VIDEO_FILE))
        print(f"  File uploaded: {VIDEO_FILE.name}", flush=True)
        file_uploaded = True
    else:
        print(f"  No video file", flush=True)
    await asyncio.sleep(3)

    # Search for file inputs that might now exist
    print("[5] Searching for file inputs...", flush=True)
    file_inputs = await page.evaluate("""() => {
        const allInputs = document.querySelectorAll('input[type="file"]');
        return Array.from(allInputs).map((el, i) => ({
            index: i,
            id: el.id,
            visible: el.offsetParent !== null,
            accept: el.accept,
            parentTag: el.parentElement ? el.parentElement.tagName : '',
        }));
    }""")
    print(f"  File inputs: {len(file_inputs)}", flush=True)
    for fi in file_inputs:
        print(f"    [{fi['index']}] id={fi['id']} visible={fi['visible']} accept={fi['accept']} parent={fi['parentTag']}", flush=True)

    if not file_inputs:
        # The hidden input might be created dynamically when menu item is clicked
        # Check if any input appeared now
        await asyncio.sleep(2)
        file_inputs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input[type="file"]')).map((el, i) => ({
                index: i, id: el.id, visible: el.offsetParent !== null, accept: el.accept
            }));
        }""")
        print(f"  File inputs (delayed check): {len(file_inputs)}", flush=True)

    # Step 3: Upload using the file input
    if file_inputs and VIDEO_FILE.exists():
        print("\n[6] Uploading via set_input_files...", flush=True)
        for fi in file_inputs:
            sel = f"input[type='file']"
            try:
                await page.locator(sel).nth(fi["index"]).set_input_files(str(VIDEO_FILE), timeout=10000)
                print(f"  Uploaded via input[{fi['index']}]", flush=True)
                results["upload"] = "set_input_files"
                break
            except Exception as e:
                print(f"  input[{fi['index']}] failed: {e}", flush=True)
        else:
            print("  All file inputs failed", flush=True)
            results["upload"] = "ALL_FAILED"
    elif not VIDEO_FILE.exists():
        print(f"[!] No video file: {VIDEO_FILE}", flush=True)
        results["upload"] = "NO_FILE"
    else:
        print("[!] No file inputs found - direct JS upload...", flush=True)
        # Use DataTransfer approach
        with open(VIDEO_FILE, "rb") as f:
            import base64
            b64 = base64.b64encode(f.read()).decode()
        result = await page.evaluate(f"""async (b64data) => {{
            const resp = await fetch('data:video/mp4;base64,' + b64data);
            const blob = await resp.blob();
            const file = new File([blob], 'hermes_demo_video.mp4', {{ type: 'video/mp4' }});
            const dt = new DataTransfer();
            dt.items.add(file);

            const dropZone = document.querySelector('ytcp-uploads-file-picker, [drag-drop]');
            if (dropZone) {{
                dropZone.dispatchEvent(new DragEvent('drop', {{
                    dataTransfer: dt, bubbles: true, cancelable: true
                }}));
                return 'drop_zone_used';
            }}

            const input = document.createElement('input');
            input.type = 'file'; input.style.display = 'none';
            document.body.appendChild(input);
            Object.defineProperty(input, 'files', {{ value: dt.files }});
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return 'js_input_created';
        }}""", b64)
        print(f"  JS upload: {result}", flush=True)
        results["upload"] = result

    # Wait for processing
    print("\n[4] Waiting for upload processing...", flush=True)
    await asyncio.sleep(10)

    try:
        await page.locator("#title-textbox, #textbox").first.wait_for(state="visible", timeout=60000)
        print("  Upload processed!", flush=True)
    except:
        print("  Upload processing check timed out", flush=True)

    # Take screenshot
    sp = Path(__file__).resolve().parent / "agent_data" / "upload_v4_state.png"
    await page.screenshot(path=str(sp))
    print(f"\n  Screenshot: {sp}", flush=True)

    results["status"] = "completed"
    rp = Path(__file__).resolve().parent / "agent_data" / "upload_v4_report.json"
    with open(rp, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Report: {rp}", flush=True)

    await ctx.close()
    await p.stop()


asyncio.run(upload_v4())
